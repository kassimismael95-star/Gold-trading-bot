#ifndef GOLD_TELEMETRY
#define GOLD_TELEMETRY
class CTelemetry
{
private:
 string eaToken;
 string Post(string url,string body)
 {
   char data[],result[]; string headers="Content-Type: application/json\r\nX-EA-Token: "+eaToken+"\r\n";
   StringToCharArray(body,data,0,WHOLE_ARRAY,CP_UTF8);
   if(ArraySize(data)>0) ArrayResize(data,ArraySize(data)-1);
   string response_headers; int code=WebRequest("POST",url,headers,5000,data,result,response_headers);
   if(code<200 || code>=300){Print("API request failed HTTP ",code," ",GetLastError());return "";}
   return CharArrayToString(result,0,-1,CP_UTF8);
 }
public:
 void SetToken(string token){eaToken=token;}
 void SendEvent(string base,string agent,long account,string kind,string payload)
 {
   string body="{\"agent_id\":\""+agent+"\",\"account_id\":"+IntegerToString(account)+",\"event_type\":\""+kind+"\",\"payload\":"+payload+"}";
   Post(base+"/api/ea/events",body);
 }
 void Heartbeat(string base,string agent,long account,string symbol,bool enabled,long magic)
 {
   int count=0; double floating=0.0;
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i); if(ticket==0)continue;
      if(PositionGetString(POSITION_SYMBOL)==symbol && PositionGetInteger(POSITION_MAGIC)==magic)
      { count++; floating+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP); }
   }
   bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   string payload="{\"symbol\":\""+symbol+"\",\"entries_enabled\":"+(enabled?"true":"false")+
      ",\"connected_to_broker\":"+(connected?"true":"false")+
      ",\"balance\":"+DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE),2)+
      ",\"equity\":"+DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY),2)+
      ",\"free_margin\":"+DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE),2)+
      ",\"floating_pnl\":"+DoubleToString(floating,2)+
      ",\"open_positions_count\":"+(string)count+"}";
   SendEvent(base,agent,account,"heartbeat",payload);
 }
 void DealsBatch(string base,long account,string dealsJson)
 {
   string body="{\"account_id\":"+IntegerToString(account)+",\"deals\":"+dealsJson+"}";
   Post(base+"/api/ea/deals/batch",body);
 }
 void TradeResult(string base,string agent,long account,string symbol,ENUM_ORDER_TYPE side,double volume,bool ok,uint retcode)
 {
   SendEvent(base,agent,account,"trade_result","{\"symbol\":\""+symbol+"\",\"side\":\""+(side==ORDER_TYPE_BUY?"BUY":"SELL")+"\",\"volume\":"+DoubleToString(volume,2)+",\"ok\":"+(ok?"true":"false")+",\"retcode\":"+(string)retcode+"}");
 }
 bool Ack(string base,long account,long commandId,string resultJson)
 {
   string body="{\"account_id\":"+IntegerToString(account)+",\"command_id\":"+IntegerToString(commandId)+",\"result\":"+resultJson+"}";
   return Post(base+"/api/ea/ack",body)!="";
 }
 bool Get(string url,string &response)
 {
   char data[],result[]; string headers=""; string response_headers;
   headers="X-EA-Token: "+eaToken+"\r\n";
   int code=WebRequest("GET",url,headers,5000,data,result,response_headers);
   if(code<200 || code>=300)return false; response=CharArrayToString(result,0,-1,CP_UTF8); return true;
 }
};
#endif
