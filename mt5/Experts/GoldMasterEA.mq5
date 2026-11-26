
#property strict
#property version   "2.00"
#property description "Gold Scalper AI - Oracle MT5 Bridge EA"

#include <Trade/Trade.mqh>

CTrade trade;

// ============================================================
// CONFIGURATION
// ============================================================

input string BridgeBaseUrl = "http://127.0.0.1:8080";
input string ApiKey = "";
input string AccountId = "";
input string TradingSymbol = "XAUUSD";

input int PollIntervalSeconds = 1;
input int RequestTimeoutMilliseconds = 5000;

input ulong MagicNumber = 9924102;

input bool PublishBrokerState = true;
input bool EnableCommandExecution = true;

// ============================================================
// GLOBAL STATE
// ============================================================

string last_processed_command = "";
datetime last_state_publish = 0;

bool bridge_connected = false;

// ============================================================
// STRING HELPERS
// ============================================================

string TrimString(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}


string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");

   return value;
}


string JsonNumber(double value, int digits = 8)
{
   return DoubleToString(value, digits);
}


string JsonBool(bool value)
{
   return value ? "true" : "false";
}


// ============================================================
// JSON READING HELPERS
// These helpers handle the simple command objects used by
// this bridge. They are not a general-purpose JSON parser.
// ============================================================

int FindValueStart(string json, string key)
{
   string search = "\"" + key + "\"";

   int key_position = StringFind(json, search);

   if(key_position < 0)
      return -1;

   int colon = StringFind(json, ":", key_position);

   if(colon < 0)
      return -1;

   int position = colon + 1;

   while(position < StringLen(json))
   {
      ushort character = StringGetCharacter(json, position);

      if(character != ' ' &&
         character != '\t' &&
         character != '\r' &&
         character != '\n')
      {
         break;
      }

      position++;
   }

   return position;
}


string ExtractString(string json, string key)
{
   int position = FindValueStart(json, key);

   if(position < 0)
      return "";

   if(StringGetCharacter(json, position) != '"')
      return "";

   position++;

   string result = "";
   bool escaped = false;

   for(int i = position; i < StringLen(json); i++)
   {
      ushort character = StringGetCharacter(json, i);

      if(escaped)
      {
         if(character == 'n')
            result += "\n";
         else if(character == 'r')
            result += "\r";
         else if(character == 't')
            result += "\t";
         else
            result += ShortToString(character);

         escaped = false;
         continue;
      }

      if(character == '\\')
      {
         escaped = true;
         continue;
      }

      if(character == '"')
         break;

      result += ShortToString(character);
   }

   return result;
}


double ExtractNumber(string json, string key, double fallback = 0.0)
{
   int position = FindValueStart(json, key);

   if(position < 0)
      return fallback;

   ushort first = StringGetCharacter(json, position);

   if(first == 'n' || first == '"' || first == '{' || first == '[')
      return fallback;

   int end = position;

   while(end < StringLen(json))
   {
      ushort c = StringGetCharacter(json, end);

      if(c == ',' || c == '}' || c == ']' ||
         c == ' ' || c == '\r' || c == '\n')
      {
         break;
      }

      end++;
   }

   string number_text = StringSubstr(
      json,
      position,
      end - position
   );

   return StringToDouble(number_text);
}


bool JsonValueIsNull(string json, string key)
{
   int position = FindValueStart(json, key);

   if(position < 0)
      return true;

   return (
      StringSubstr(json, position, 4) == "null"
   );
}


bool JsonValueExists(string json, string key)
{
   return FindValueStart(json, key) >= 0;
}


// ============================================================
// HTTP CLIENT
// ============================================================

bool HttpRequest(
   string method,
   string endpoint,
   string payload,
   string &response
)
{
   response = "";

   if(ApiKey == "")
   {
      Print("ERROR: Bridge API key is missing.");
      return false;
   }

   string url = BridgeBaseUrl + endpoint;

   string headers =
      "Content-Type: application/json\r\n"
      "Authorization: Bearer " + ApiKey + "\r\n";

   char request_data[];
   char response_data[];

   if(payload != "")
   {
      int copied = StringToCharArray(
         payload,
         request_data,
         0,
         WHOLE_ARRAY,
         CP_UTF8
      );

      if(copied > 0)
         ArrayResize(request_data, copied - 1);
   }
   else
   {
      ArrayResize(request_data, 0);
   }

   string response_headers;

   ResetLastError();

   int result = WebRequest(
      method,
      url,
      headers,
      RequestTimeoutMilliseconds,
      request_data,
      response_data,
      response_headers
   );

   if(result == -1)
   {
      Print(
         "Bridge HTTP error: ",
         GetLastError(),
         " endpoint=",
         endpoint
      );

      bridge_connected = false;
      return false;
   }

   response = CharArrayToString(
      response_data,
      0,
      -1,
      CP_UTF8
   );

   if(result < 200 || result >= 300)
   {
      Print(
         "Bridge returned HTTP ",
         result,
         ": ",
         response
      );

      bridge_connected = false;
      return false;
   }

   bridge_connected = true;
   return true;
}


// ============================================================
// BROKER RETCODE CHECK
// ============================================================

bool TradeResultAccepted()
{
   uint retcode = trade.ResultRetcode();

   return (
      retcode == TRADE_RETCODE_DONE ||
      retcode == TRADE_RETCODE_DONE_PARTIAL ||
      retcode == TRADE_RETCODE_PLACED
   );
}


// ============================================================
// SYMBOL HELPERS
// ============================================================

bool EnsureSymbolSelected(string symbol)
{
   if(symbol == "")
      return false;

   if(!SymbolSelect(symbol, true))
   {
      Print("Could not select symbol: ", symbol);
      return false;
   }

   return true;
}


double NormalizeVolumeDown(string symbol, double volume)
{
   double step = SymbolInfoDouble(
      symbol,
      SYMBOL_VOLUME_STEP
   );

   double minimum = SymbolInfoDouble(
      symbol,
      SYMBOL_VOLUME_MIN
   );

   double maximum = SymbolInfoDouble(
      symbol,
      SYMBOL_VOLUME_MAX
   );

   if(step <= 0 || minimum <= 0 || maximum <= 0)
      return 0.0;

   if(volume > maximum)
      volume = maximum;

   volume = MathFloor(volume / step) * step;

   int digits = 0;

   while(digits < 8 &&
         MathAbs(step - NormalizeDouble(step, digits)) > 0.000000001)
   {
      digits++;
   }

   volume = NormalizeDouble(volume, digits);

   if(volume < minimum)
      return 0.0;

   return volume;
}


bool PositionExists(ulong ticket)
{
   return PositionSelectByTicket(ticket);
}


// ============================================================
// COMMAND RESULT REPORTING
// ============================================================

void ReportCommandResult(
   string command_id,
   bool success,
   string message,
   ulong position_id = 0,
   ulong order_ticket = 0
)
{
   string endpoint =
      "/commands/" + command_id + "/result";

   string payload =
      "{"
      "\"success\":" + JsonBool(success) + ","
      "\"message\":\"" + JsonEscape(message) + "\","
      "\"retcode\":" +
         IntegerToString((int)trade.ResultRetcode()) + ","
      "\"retcode_description\":\"" +
         JsonEscape(trade.ResultRetcodeDescription()) + "\","
      "\"position_id\":" +
         IntegerToString((long)position_id) + ","
      "\"order_ticket\":" +
         IntegerToString((long)order_ticket)
      "}";

   string response;

   if(!HttpRequest("POST", endpoint, payload, response))
   {
      Print(
         "Could not report command result. Command ID: ",
         command_id
      );
   }
}


// ============================================================
// OPEN MARKET POSITION
// ============================================================

bool ExecuteOpenPosition(
   string command,
   ulong &position_id,
   ulong &order_ticket
)
{
   position_id = 0;
   order_ticket = 0;

   string symbol = ExtractString(command, "symbol");

   if(symbol == "")
      symbol = TradingSymbol;

   if(!EnsureSymbolSelected(symbol))
      return false;

   string direction = ExtractString(command, "direction");

   if(direction == "")
      direction = ExtractString(command, "side");

   double volume = ExtractNumber(command, "volume", 0.0);

   double stop_loss = ExtractNumber(command, "stop_loss", 0.0);
   double take_profit = ExtractNumber(command, "take_profit", 0.0);

   if(volume <= 0)
   {
      Print("Rejected order: invalid volume.");
      return false;
   }

   double normalized_volume = NormalizeVolumeDown(
      symbol,
      volume
   );

   if(normalized_volume <= 0)
   {
      Print(
         "Rejected order: requested volume does not meet ",
         "broker volume requirements."
      );

      return false;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetTypeFillingBySymbol(symbol);

   bool request_accepted = false;

   if(StringCompare(direction, "BUY", false) == 0)
   {
      request_accepted = trade.Buy(
         normalized_volume,
         symbol,
         0.0,
         stop_loss,
         take_profit,
         "GOLD-SCALPER-AI"
      );
   }
   else if(StringCompare(direction, "SELL", false) == 0)
   {
      request_accepted = trade.Sell(
         normalized_volume,
         symbol,
         0.0,
         stop_loss,
         take_profit,
         "GOLD-SCALPER-AI"
      );
   }
   else
   {
      Print("Rejected order: direction must be BUY or SELL.");
      return false;
   }

   if(!request_accepted || !TradeResultAccepted())
   {
      Print(
         "Order rejected: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   order_ticket = trade.ResultOrder();

   // ResultDeal is not the same thing as a position ticket.
   // Resolve the actual position identifier from deal history.
   ulong deal_ticket = trade.ResultDeal();

   if(deal_ticket > 0 && HistoryDealSelect(deal_ticket))
   {
      position_id = (ulong)HistoryDealGetInteger(
         deal_ticket,
         DEAL_POSITION_ID
      );
   }

   if(position_id == 0)
   {
      Print(
         "MT5 accepted the request but the position identifier ",
         "has not yet been verified. Broker snapshot reconciliation ",
         "is required."
      );
   }

   return true;
}


// ============================================================
// MODIFY INDIVIDUAL POSITION
// ============================================================

bool ExecuteModifyPosition(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id",
      0
   );

   if(ticket == 0)
      ticket = (ulong)ExtractNumber(
         command,
         "ticket",
         0
      );

   if(ticket == 0 || !PositionSelectByTicket(ticket))
   {
      Print("Modify rejected: position not found.");
      return false;
   }

   string symbol = PositionGetString(POSITION_SYMBOL);

   double current_sl = PositionGetDouble(POSITION_SL);
   double current_tp = PositionGetDouble(POSITION_TP);

   double new_sl = current_sl;
   double new_tp = current_tp;

   if(JsonValueExists(command, "stop_loss") &&
      !JsonValueIsNull(command, "stop_loss"))
   {
      new_sl = ExtractNumber(
         command,
         "stop_loss",
         current_sl
      );
   }

   if(JsonValueExists(command, "take_profit") &&
      !JsonValueIsNull(command, "take_profit"))
   {
      new_tp = ExtractNumber(
         command,
         "take_profit",
         current_tp
      );
   }

   // Never allow this EA to move an existing stop backwards.
   ENUM_POSITION_TYPE position_type =
      (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   if(position_type == POSITION_TYPE_BUY &&
      current_sl > 0 &&
      new_sl > 0 &&
      new_sl < current_sl)
   {
      Print("Rejected modification: BUY stop would move backwards.");
      return false;
   }

   if(position_type == POSITION_TYPE_SELL &&
      current_sl > 0 &&
      new_sl > 0 &&
      new_sl > current_sl)
   {
      Print("Rejected modification: SELL stop would move backwards.");
      return false;
   }

   int digits = (int)SymbolInfoInteger(
      symbol,
      SYMBOL_DIGITS
   );

   if(new_sl > 0)
      new_sl = NormalizeDouble(new_sl, digits);

   if(new_tp > 0)
      new_tp = NormalizeDouble(new_tp, digits);

   trade.SetExpertMagicNumber(MagicNumber);

   bool accepted = trade.PositionModify(
      ticket,
      new_sl,
      new_tp
   );

   if(!accepted || !TradeResultAccepted())
   {
      Print(
         "Position modification failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   // Verify the position still exists and the requested
   // broker-side values were applied.
   if(!PositionSelectByTicket(ticket))
      return false;

   double verified_sl = PositionGetDouble(POSITION_SL);
   double verified_tp = PositionGetDouble(POSITION_TP);

   double tolerance = SymbolInfoDouble(
      symbol,
      SYMBOL_POINT
   ) * 2.0;

   if(new_sl > 0 &&
      MathAbs(verified_sl - new_sl) > tolerance)
   {
      Print("Stop-loss modification not verified.");
      return false;
   }

   if(new_tp > 0 &&
      MathAbs(verified_tp - new_tp) > tolerance)
   {
      Print("Take-profit modification not verified.");
      return false;
   }

   return true;
}


// ============================================================
// CLOSE INDIVIDUAL POSITION
// ============================================================

bool ExecuteClosePosition(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id",
      0
   );

   if(ticket == 0)
      ticket = (ulong)ExtractNumber(
         command,
         "ticket",
         0
      );

   if(ticket == 0 || !PositionSelectByTicket(ticket))
   {
      Print("Close rejected: position not found.");
      return false;
   }

   trade.SetExpertMagicNumber(MagicNumber);

   bool accepted = trade.PositionClose(ticket);

   if(!accepted || !TradeResultAccepted())
   {
      Print(
         "Position close failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   // Verify the position is no longer open.
   if(PositionSelectByTicket(ticket))
   {
      Print("Position close was not verified.");
      return false;
   }

   return true;
}


// ============================================================
// PARTIAL CLOSE
// ============================================================

bool ExecutePartialClose(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id",
      0
   );

   if(ticket == 0)
      ticket = (ulong)ExtractNumber(
         command,
         "ticket",
         0
      );

   if(ticket == 0 || !PositionSelectByTicket(ticket))
   {
      Print("Partial close rejected: position not found.");
      return false;
   }

   string symbol = PositionGetString(POSITION_SYMBOL);

   double current_volume = PositionGetDouble(
      POSITION_VOLUME
   );

   double requested_volume = ExtractNumber(
      command,
      "volume",
      0.0
   );

   if(requested_volume <= 0 ||
      requested_volume >= current_volume)
   {
      Print("Partial close rejected: invalid requested volume.");
      return false;
   }

   double close_volume = NormalizeVolumeDown(
      symbol,
      requested_volume
   );

   if(close_volume <= 0 || close_volume >= current_volume)
   {
      Print(
         "Partial close rejected: volume does not satisfy ",
         "broker volume requirements."
      );

      return false;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetTypeFillingBySymbol(symbol);

   ENUM_ACCOUNT_MARGIN_MODE margin_mode =
      (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(
         ACCOUNT_MARGIN_MODE
      );

   bool accepted = false;

   if(margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      accepted = trade.PositionClosePartial(
         ticket,
         close_volume
      );
   }
   else
   {
      // On a netting account, an opposite deal reduces the
      // existing net position. The volume must remain below
      // the existing position volume.
      ENUM_POSITION_TYPE position_type =
         (ENUM_POSITION_TYPE)PositionGetInteger(
            POSITION_TYPE
         );

      if(position_type == POSITION_TYPE_BUY)
      {
         accepted = trade.Sell(
            close_volume,
            symbol,
            0.0,
            0.0,
            0.0,
            "GOLD-SCALPER-PARTIAL-CLOSE"
         );
      }
      else
      {
         accepted = trade.Buy(
            close_volume,
            symbol,
            0.0,
            0.0,
            0.0,
            "GOLD-SCALPER-PARTIAL-CLOSE"
         );
      }
   }

   if(!accepted || !TradeResultAccepted())
   {
      Print(
         "Partial close failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   if(!PositionSelectByTicket(ticket))
   {
      Print(
         "Original position no longer exists after partial close."
      );

      return false;
   }

   double remaining_volume = PositionGetDouble(
      POSITION_VOLUME
   );

   if(remaining_volume >= current_volume)
   {
      Print("Partial close could not be verified.");
      return false;
   }

   return true;
}


// ============================================================
// COMMAND EXECUTION ROUTER
// ============================================================

void ProcessCommand(string response)
{
   string command_id = ExtractString(
      response,
      "command_id"
   );

   if(command_id == "")
      return;

   if(command_id == last_processed_command)
      return;

   int command_position = StringFind(
      response,
      "\"command\""
   );

   if(command_position < 0)
      return;

   string command = StringSubstr(
      response,
      command_position
   );

   string action = ExtractString(command, "action");

   if(action == "")
      action = ExtractString(command, "type");

   bool success = false;

   ulong position_id = 0;
   ulong order_ticket = 0;

   if(action == "open_market_position")
   {
      success = ExecuteOpenPosition(
         command,
         position_id,
         order_ticket
      );
   }
   else if(action == "modify_position")
   {
      position_id = (ulong)ExtractNumber(
         command,
         "position_id",
         0
      );

      success = ExecuteModifyPosition(command);
   }
   else if(action == "close_position")
   {
      position_id = (ulong)ExtractNumber(
         command,
         "position_id",
         0
      );

      success = ExecuteClosePosition(command);
   }
   else if(action == "partial_close")
   {
      position_id = (ulong)ExtractNumber(
         command,
         "position_id",
         0
      );

      success = ExecutePartialClose(command);
   }
   else
   {
      Print("Unknown command action: ", action);
      success = false;
   }

   string message = success
      ? "MT5 action accepted and verification passed where available"
      : "MT5 action failed or broker-state verification failed";

   ReportCommandResult(
      command_id,
      success,
      message,
      position_id,
      order_ticket
   );

   last_processed_command = command_id;
}


// ============================================================
// COMMAND POLLING
// ============================================================

void PollBridgeCommands()
{
   if(!EnableCommandExecution)
      return;

   if(AccountId == "")
   {
      Print("Cannot poll: AccountId is missing.");
      return;
   }

   string endpoint =
      "/commands/next?account_id=" + AccountId;

   string response;

   if(!HttpRequest(
      "GET",
      endpoint,
      "",
      response
   ))
   {
      return;
   }

   string command_id = ExtractString(
      response,
      "command_id"
   );

   if(command_id == "")
      return;

   ProcessCommand(response);
}


// ============================================================
// POSITION SNAPSHOT
// ============================================================

string BuildPositionsJson()
{
   string result = "[";
   bool first = true;

   int total = PositionsTotal();

   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);

      if(ticket == 0)
         continue;

      if(!PositionSelectByTicket(ticket))
         continue;

      string symbol = PositionGetString(
         POSITION_SYMBOL
      );

      long position_type = PositionGetInteger(
         POSITION_TYPE
      );

      string direction =
         position_type == POSITION_TYPE_BUY
         ? "BUY"
         : "SELL";

      double volume = PositionGetDouble(
         POSITION_VOLUME
      );

      double entry_price = PositionGetDouble(
         POSITION_PRICE_OPEN
      );

      double current_price = PositionGetDouble(
         POSITION_PRICE_CURRENT
      );

      double stop_loss = PositionGetDouble(
         POSITION_SL
      );

      double take_profit = PositionGetDouble(
         POSITION_TP
      );

      double profit = PositionGetDouble(
         POSITION_PROFIT
      );

      double swap = PositionGetDouble(
         POSITION_SWAP
      );

      long magic = PositionGetInteger(
         POSITION_MAGIC
      );

      long time_msc = PositionGetInteger(
         POSITION_TIME_MSC
      );

      if(!first)
         result += ",";

      first = false;

      result +=
         "{"
         "\"position_id\":" +
            IntegerToString((long)ticket) + ","
         "\"ticket\":" +
            IntegerToString((long)ticket) + ","
         "\"symbol\":\"" +
            JsonEscape(symbol) + "\","
         "\"direction\":\"" +
            direction + "\","
         "\"type\":\"" +
            direction + "\","
         "\"volume\":" +
            JsonNumber(volume, 8) + ","
         "\"entry_price\":" +
            JsonNumber(entry_price, 8) + ","
         "\"current_price\":" +
            JsonNumber(current_price, 8) + ","
         "\"stop_loss\":" +
            JsonNumber(stop_loss, 8) + ","
         "\"take_profit\":" +
            JsonNumber(take_profit, 8) + ","
         "\"profit\":" +
            JsonNumber(profit, 2) + ","
         "\"swap\":" +
            JsonNumber(swap, 2) + ","
         "\"magic_number\":" +
            IntegerToString(magic) + ","
         "\"time_msc\":" +
            IntegerToString(time_msc)
         "}";

   }

   result += "]";
   return result;
}


// ============================================================
// ACCOUNT SNAPSHOT
// ============================================================

string BuildAccountJson()
{
   double balance = AccountInfoDouble(
      ACCOUNT_BALANCE
   );

   double equity = AccountInfoDouble(
      ACCOUNT_EQUITY
   );

   double free_margin = AccountInfoDouble(
      ACCOUNT_MARGIN_FREE
   );

   double margin = AccountInfoDouble(
      ACCOUNT_MARGIN
   );

   double margin_level = AccountInfoDouble(
      ACCOUNT_MARGIN_LEVEL
   );

   long login = AccountInfoInteger(
      ACCOUNT_LOGIN
   );

   string server = AccountInfoString(
      ACCOUNT_SERVER
   );

   string currency = AccountInfoString(
      ACCOUNT_CURRENCY
   );

   return
      "{"
      "\"login\":" +
         IntegerToString(login) + ","
      "\"server\":\"" +
         JsonEscape(server) + "\","
      "\"currency\":\"" +
         JsonEscape(currency) + "\","
      "\"balance\":" +
         JsonNumber(balance, 2) + ","
      "\"equity\":" +
         JsonNumber(equity, 2) + ","
      "\"free_margin\":" +
         JsonNumber(free_margin, 2) + ","
      "\"margin\":" +
         JsonNumber(margin, 2) + ","
      "\"margin_level\":" +
         JsonNumber(margin_level, 2)
      "}";
}


// ============================================================
// PRICE SNAPSHOT
// ============================================================

string BuildPricesJson()
{
   string result = "{";

   string symbol = TradingSymbol;

   if(!EnsureSymbolSelected(symbol))
   {
      result += "}";
      return result;
   }

   MqlTick tick;

   if(!SymbolInfoTick(symbol, tick))
   {
      result += "}";
      return result;
   }

   result +=
      "\"" + JsonEscape(symbol) + "\":{"
      "\"bid\":" + JsonNumber(tick.bid, 8) + ","
      "\"ask\":" + JsonNumber(tick.ask, 8) + ","
      "\"last\":" + JsonNumber(tick.last, 8) + ","
      "\"time_msc\":" +
         IntegerToString((long)tick.time_msc)
      "}";

   result += "}";

   return result;
}


// ============================================================
// PUBLISH BROKER STATE TO ORACLE BRIDGE
// ============================================================

void PublishState()
{
   if(!PublishBrokerState)
      return;

   if(AccountId == "")
      return;

   string account_json = BuildAccountJson();
   string positions_json = BuildPositionsJson();
   string prices_json = BuildPricesJson();

   string payload =
      "{"
      "\"account_id\":\"" +
         JsonEscape(AccountId) + "\","
      "\"account\":" + account_json + ","
      "\"positions\":" + positions_json + ","
      "\"prices\":" + prices_json
      "}";

   string response;

   if(HttpRequest(
      "POST",
      "/state",
      payload,
      response
   ))
   {
      last_state_publish = TimeCurrent();
   }
}


// ============================================================
// INITIALIZATION
// ============================================================

int OnInit()
{
   if(ApiKey == "")
   {
      Print("ERROR: Configure ApiKey before attaching the EA.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(AccountId == "")
   {
      Print("ERROR: Configure AccountId before attaching the EA.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(PollIntervalSeconds < 1)
   {
      Print("ERROR: PollIntervalSeconds must be at least 1.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(!EnsureSymbolSelected(TradingSymbol))
   {
      Print("ERROR: Trading symbol is unavailable: ", TradingSymbol);
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetTypeFillingBySymbol(TradingSymbol);
   trade.SetAsyncMode(false);

   EventSetTimer(PollIntervalSeconds);

   Print("Gold Scalper AI EA initialized.");
   Print("Account ID: ", AccountId);
   Print("Symbol: ", TradingSymbol);
   Print("Bridge: ", BridgeBaseUrl);

   // Publish an initial snapshot.
   PublishState();

   return INIT_SUCCEEDED;
}


// ============================================================
// TIMER
// ============================================================

void OnTimer()
{
   // Publish current broker state before processing commands.
   PublishState();

   // Retrieve commands assigned to this account only.
   PollBridgeCommands();
}


// ============================================================
// DEINITIALIZATION
// ============================================================

void OnDeinit(const int reason)
{
   EventKillTimer();

   Print(
      "Gold Scalper AI EA stopped. Reason: ",
      reason
   );
}
