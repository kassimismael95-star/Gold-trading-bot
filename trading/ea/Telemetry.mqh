
#ifndef GOLD_TELEMETRY
#define GOLD_TELEMETRY

// Gold Scalper AI - account telemetry and API communication.
// Preserves the existing public interface.

class CTelemetry
{
private:
   string eaToken;

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

   string Post(string url, string body)
   {
      if(eaToken == "")
      {
         Print("Telemetry unavailable: EA token is not configured.");
         return "";
      }

      char data[];
      char result[];

      string headers =
         "Content-Type: application/json\r\n" +
         "X-EA-Token: " + eaToken + "\r\n";

      StringToCharArray(
         body,
         data,
         0,
         WHOLE_ARRAY,
         CP_UTF8
      );

      if(ArraySize(data) > 0)
         ArrayResize(data, ArraySize(data) - 1);

      string responseHeaders;

      ResetLastError();

      int code = WebRequest(
         "POST",
         url,
         headers,
         5000,
         data,
         result,
         responseHeaders
      );

      if(code < 200 || code >= 300)
      {
         Print(
            "Telemetry POST failed. HTTP=",
            code,
            " Error=",
            GetLastError()
         );

         return "";
      }

      return CharArrayToString(
         result,
         0,
         -1,
         CP_UTF8
      );
   }

public:

   CTelemetry()
   {
      eaToken = "";
   }

   void SetToken(string token)
   {
      eaToken = token;
   }

   void SendEvent(
      string base,
      string agent,
      long account,
      string kind,
      string payload
   )
   {
      if(base == "" || agent == "" || account <= 0 || kind == "")
         return;

      string body =
         "{\"agent_id\":\"" + JsonEscape(agent) +
         "\",\"account_id\":" + (string)account +
         ",\"event_type\":\"" + JsonEscape(kind) +
         "\",\"payload\":" + payload + "}";

      Post(
         base + "/api/ea/events",
         body
      );
   }

   void Heartbeat(
      string base,
      string agent,
      long account,
      string symbol,
      bool enabled,
      long magic
   )
   {
      if(base == "" || agent == "" || account <= 0 || symbol == "")
         return;

      int count = 0;
      double floating = 0.0;

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(!PositionSelectByTicket(ticket))
            continue;

         if(PositionGetString(POSITION_SYMBOL) != symbol)
            continue;

         if(PositionGetInteger(POSITION_MAGIC) != magic)
            continue;

         count++;

         floating +=
            PositionGetDouble(POSITION_PROFIT) +
            PositionGetDouble(POSITION_SWAP);
      }

      bool connected =
         (bool)TerminalInfoInteger(TERMINAL_CONNECTED);

      double balance =
         AccountInfoDouble(ACCOUNT_BALANCE);

      double equity =
         AccountInfoDouble(ACCOUNT_EQUITY);

      double freeMargin =
         AccountInfoDouble(ACCOUNT_MARGIN_FREE);

      double margin =
         AccountInfoDouble(ACCOUNT_MARGIN);

      double marginLevel =
         AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);

      string payload =
         "{\"symbol\":\"" + JsonEscape(symbol) +
         "\",\"entries_enabled\":" +
         (enabled ? "true" : "false") +
         ",\"connected_to_broker\":" +
         (connected ? "true" : "false") +
         ",\"balance\":" + JsonNumber(balance, 2) +
         ",\"equity\":" + JsonNumber(equity, 2) +
         ",\"free_margin\":" + JsonNumber(freeMargin, 2) +
         ",\"used_margin\":" + JsonNumber(margin, 2) +
         ",\"margin_level\":" + JsonNumber(marginLevel, 2) +
         ",\"floating_pnl\":" + JsonNumber(floating, 2) +
         ",\"open_positions_count\":" + (string)count +
         "}";

      SendEvent(
         base,
         agent,
         account,
         "heartbeat",
         payload
      );
   }

   void DealsBatch(
      string base,
      long account,
      string dealsJson
   )
   {
      if(base == "" || account <= 0 || dealsJson == "")
         return;

      string body =
         "{\"account_id\":" + (string)account +
         ",\"deals\":" + dealsJson + "}";

      Post(
         base + "/api/ea/deals/batch",
         body
      );
   }

   void TradeResult(
      string base,
      string agent,
      long account,
      string symbol,
      ENUM_ORDER_TYPE side,
      double volume,
      bool ok,
      uint retcode
   )
   {
      if(side != ORDER_TYPE_BUY && side != ORDER_TYPE_SELL)
         return;

      string sideText =
         (side == ORDER_TYPE_BUY ? "BUY" : "SELL");

      string payload =
         "{\"symbol\":\"" + JsonEscape(symbol) +
         "\",\"side\":\"" + sideText +
         "\",\"volume\":" + JsonNumber(volume, 8) +
         ",\"ok\":" + (ok ? "true" : "false") +
         ",\"retcode\":" + (string)retcode +
         "}";

      SendEvent(
         base,
         agent,
         account,
         "trade_result",
         payload
      );
   }

   bool Ack(
      string base,
      long account,
      long commandId,
      string resultJson
   )
   {
      if(base == "" || account <= 0 || commandId <= 0 ||
         resultJson == "")
         return false;

      string body =
         "{\"account_id\":" + (string)account +
         ",\"command_id\":" + (string)commandId +
         ",\"result\":" + resultJson + "}";

      return Post(
         base + "/api/ea/ack",
         body
      ) != "";
   }

   bool Get(
      string url,
      string &response
   )
   {
      response = "";

      if(eaToken == "" || url == "")
         return false;

      char data[];
      char result[];

      string headers =
         "X-EA-Token: " + eaToken + "\r\n";

      string responseHeaders;

      ResetLastError();

      int code = WebRequest(
         "GET",
         url,
         headers,
         5000,
         data,
         result,
         responseHeaders
      );

      if(code < 200 || code >= 300)
      {
         Print(
            "Telemetry GET failed. HTTP=",
            code,
            " Error=",
            GetLastError()
         );

         return false;
      }

      response = CharArrayToString(
         result,
         0,
         -1,
         CP_UTF8
      );

      return true;
   }
};

#endif
