
#property strict
#property version   "1.00"
#property description "Gold Master EA - Oracle Cloud Python Bridge"

#include <Trade/Trade.mqh>

CTrade trade;

// ======================================================
// CONFIGURATION
// ======================================================

input string BridgeBaseUrl = "http://127.0.0.1:8080";
input string ApiKey = "";
input string AccountId = "";
input int PollIntervalSeconds = 1;
input int RequestTimeoutMilliseconds = 5000;
input ulong MagicNumber = 9924102;

// ======================================================
// GLOBAL STATE
// ======================================================

string last_processed_command = "";
bool bridge_connected = false;

// ======================================================
// JSON HELPERS
// ======================================================

string JsonString(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\r", "\\r");

   return "\"" + value + "\"";
}

string ExtractString(string json, string key)
{
   string search = "\"" + key + "\"";
   int position = StringFind(json, search);

   if(position < 0)
      return "";

   position = StringFind(json, ":", position);

   if(position < 0)
      return "";

   position++;

   while(position < StringLen(json))
   {
      ushort c = StringGetCharacter(json, position);

      if(c != ' ' && c != '\t')
         break;

      position++;
   }

   if(StringGetCharacter(json, position) != '"')
      return "";

   position++;

   string output = "";
   bool escaped = false;

   for(int i = position; i < StringLen(json); i++)
   {
      ushort c = StringGetCharacter(json, i);

      if(escaped)
      {
         if(c == 'n')
            output += "\n";
         else if(c == 'r')
            output += "\r";
         else
            output += ShortToString(c);

         escaped = false;
         continue;
      }

      if(c == '\\')
      {
         escaped = true;
         continue;
      }

      if(c == '"')
         return output;

      output += ShortToString(c);
   }

   return "";
}

double ExtractNumber(string json, string key)
{
   string search = "\"" + key + "\"";
   int position = StringFind(json, search);

   if(position < 0)
      return 0.0;

   position = StringFind(json, ":", position);

   if(position < 0)
      return 0.0;

   position++;

   while(position < StringLen(json))
   {
      ushort c = StringGetCharacter(json, position);

      if(c != ' ' && c != '\t')
         break;

      position++;
   }

   int end = position;

   while(end < StringLen(json))
   {
      ushort c = StringGetCharacter(json, end);

      if(
         (c >= '0' && c <= '9') ||
         c == '-' ||
         c == '+' ||
         c == '.'
      )
      {
         end++;
      }
      else
      {
         break;
      }
   }

   if(end <= position)
      return 0.0;

   return StringToDouble(
      StringSubstr(json, position, end - position)
   );
}

string ExtractCommandObject(string json)
{
   int position = StringFind(json, "\"command\"");

   if(position < 0)
      return "";

   position = StringFind(json, "{", position);

   if(position < 0)
      return "";

   int depth = 0;
   bool inside_string = false;
   bool escaped = false;

   for(int i = position; i < StringLen(json); i++)
   {
      ushort c = StringGetCharacter(json, i);

      if(inside_string)
      {
         if(escaped)
         {
            escaped = false;
            continue;
         }

         if(c == '\\')
         {
            escaped = true;
            continue;
         }

         if(c == '"')
            inside_string = false;

         continue;
      }

      if(c == '"')
      {
         inside_string = true;
         continue;
      }

      if(c == '{')
         depth++;

      if(c == '}')
      {
         depth--;

         if(depth == 0)
            return StringSubstr(
               json,
               position,
               i - position + 1
            );
      }
   }

   return "";
}

// ======================================================
// HTTP HELPERS
// ======================================================

bool HttpRequest(
   string method,
   string path,
   string payload,
   string &response
)
{
   string url = BridgeBaseUrl + path;

   string headers =
      "Content-Type: application/json\r\n"
      "Accept: application/json\r\n";

   if(ApiKey != "")
      headers += "Authorization: Bearer " + ApiKey + "\r\n";

   char request_data[];
   char response_data[];

   if(payload != "")
   {
      int size = StringToCharArray(
         payload,
         request_data,
         0,
         WHOLE_ARRAY,
         CP_UTF8
      );

      if(size > 0)
         ArrayResize(request_data, size - 1);
   }

   string response_headers;

   ResetLastError();

   int status = WebRequest(
      method,
      url,
      headers,
      RequestTimeoutMilliseconds,
      request_data,
      response_data,
      response_headers
   );

   if(status == -1)
   {
      Print(
         "Bridge communication failed. Error: ",
         GetLastError()
      );

      bridge_connected = false;
      return false;
   }

   if(status < 200 || status >= 300)
   {
      Print("Bridge HTTP status: ", status);
      bridge_connected = false;
      return false;
   }

   response = CharArrayToString(
      response_data,
      0,
      WHOLE_ARRAY,
      CP_UTF8
   );

   bridge_connected = true;

   return true;
}

// ======================================================
// COMMAND ACKNOWLEDGEMENT
// ======================================================

void ReportCommandResult(
   string command_id,
   bool success,
   string message,
   ulong position_id = 0
)
{
   string payload =
      "{"
      "\"account_id\":" + JsonString(AccountId) + ","
      "\"command_id\":" + JsonString(command_id) + ","
      "\"success\":" + (success ? "true" : "false") + ","
      "\"message\":" + JsonString(message) + ","
      "\"position_id\":" + IntegerToString((long)position_id)
      "}";

   string response;

   HttpRequest(
      "POST",
      "/commands/" + command_id + "/result",
      payload,
      response
   );
}

// ======================================================
// POSITION IDENTIFICATION
// ======================================================

bool FindPosition(ulong ticket)
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong current_ticket = PositionGetTicket(i);

      if(current_ticket == ticket)
         return true;
   }

   return false;
}

// ======================================================
// EXECUTION FUNCTIONS
// ======================================================

bool ExecuteOpenPosition(
   string command,
   ulong &position_id
)
{
   string symbol = ExtractString(command, "symbol");
   string direction = ExtractString(command, "direction");

   double volume = ExtractNumber(command, "volume");
   double sl = ExtractNumber(command, "stop_loss");
   double tp = ExtractNumber(command, "take_profit");

   if(symbol == "" || volume <= 0)
      return false;

   if(!SymbolSelect(symbol, true))
   {
      Print("Cannot select symbol: ", symbol);
      return false;
   }

   bool result = false;

   if(direction == "BUY")
   {
      result = trade.Buy(
         volume,
         symbol,
         0.0,
         sl,
         tp,
         "GOLD-MASTER-BUY"
      );
   }
   else if(direction == "SELL")
   {
      result = trade.Sell(
         volume,
         symbol,
         0.0,
         sl,
         tp,
         "GOLD-MASTER-SELL"
      );
   }
   else
   {
      return false;
   }

   if(!result)
   {
      Print(
         "Order failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   position_id = trade.ResultOrder();

   Print(
      "Order request accepted. Retcode: ",
      trade.ResultRetcodeDescription()
   );

   return true;
}

bool ExecuteModifyPosition(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id"
   );

   if(ticket == 0 || !FindPosition(ticket))
      return false;

   double sl = ExtractNumber(command, "stop_loss");
   double tp = ExtractNumber(command, "take_profit");

   bool has_sl = StringFind(command, "\"stop_loss\":null") < 0;
   bool has_tp = StringFind(command, "\"take_profit\":null") < 0;

   double current_sl = PositionGetDouble(POSITION_SL);
   double current_tp = PositionGetDouble(POSITION_TP);

   if(!has_sl)
      sl = current_sl;

   if(!has_tp)
      tp = current_tp;

   bool result = trade.PositionModify(
      ticket,
      sl,
      tp
   );

   if(!result)
   {
      Print(
         "Position modification failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   return true;
}

bool ExecuteClosePosition(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id"
   );

   if(ticket == 0 || !FindPosition(ticket))
      return false;

   bool result = trade.PositionClose(ticket);

   if(!result)
   {
      Print(
         "Position close failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   return true;
}

bool ExecutePartialClose(string command)
{
   ulong ticket = (ulong)ExtractNumber(
      command,
      "position_id"
   );

   double volume = ExtractNumber(
      command,
      "volume"
   );

   if(ticket == 0 || volume <= 0)
      return false;

   if(!FindPosition(ticket))
      return false;

   bool result = trade.PositionClosePartial(
      ticket,
      volume
   );

   if(!result)
   {
      Print(
         "Partial close failed: ",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   return true;
}

// ======================================================
// COMMAND ROUTER
// ======================================================

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

   string command = ExtractCommandObject(response);

   if(command == "")
      return;

   string type = ExtractString(
      command,
      "type"
   );

   bool success = false;
   ulong position_id = 0;

   if(type == "open_market_position")
   {
      success = ExecuteOpenPosition(
         command,
         position_id
      );
   }
   else if(type == "modify_position")
   {
      success = ExecuteModifyPosition(command);
   }
   else if(type == "close_position")
   {
      success = ExecuteClosePosition(command);
   }
   else if(type == "partial_close")
   {
      success = ExecutePartialClose(command);
   }
   else
   {
      Print("Unsupported command: ", type);
      return;
   }

   last_processed_command = command_id;

   ReportCommandResult(
      command_id,
      success,
      success ? "MT5 request accepted" : "MT5 execution failed",
      position_id
   );
}

// ======================================================
// BRIDGE POLLING
// ======================================================

void PollBridge()
{
   if(AccountId == "")
      return;

   string response;

   string path =
      "/commands/next?account_id=" +
      AccountId;

   if(!HttpRequest("GET", path, "", response))
      return;

   if(StringFind(response, "\"command_id\"") < 0)
      return;

   ProcessCommand(response);
}

// ======================================================
// INITIALIZATION
// ======================================================

int OnInit()
{
   if(AccountId == "")
   {
      Print("ERROR: AccountId is required.");
      return INIT_PARAMETERS_INCORRECT;
   }

   if(PollIntervalSeconds < 1)
   {
      Print("ERROR: Poll interval must be at least 1 second.");
      return INIT_PARAMETERS_INCORRECT;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetAsyncMode(false);

   EventSetTimer(PollIntervalSeconds);

   Print("Gold Master EA initialized.");
   Print("Oracle bridge: ", BridgeBaseUrl);
   Print("Account ID: ", AccountId);

   return INIT_SUCCEEDED;
}

// ======================================================
// TIMER
// ======================================================

void OnTimer()
{
   PollBridge();
}

// ======================================================
// TICK EVENT
// ======================================================

void OnTick()
{
   // The original Python entry engine and live intelligence
   // remain responsible for trading decisions.
   //
   // This EA executes commands received from Python.
   //
   // Broker-side SL/TP remain active independently.
}

// ======================================================
// SHUTDOWN
// ======================================================

void OnDeinit(const int reason)
{
   EventKillTimer();

   Print(
      "Gold Master EA stopped. Reason: ",
      reason
   );
}
