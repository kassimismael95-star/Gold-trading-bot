
#property strict
#property version "1.03"
#property description "Gold Scalper EA - original entries; independent post-entry intelligence; demo and authorized live"

#include <Trade/Trade.mqh>
#include "SignalEngine.mqh"
#include "RiskManager.mqh"
#include "PositionManager.mqh"
#include "ExecutionManager.mqh"
#include "AdaptiveManager.mqh"
#include "Telemetry.mqh"
#include "BrokerSpecification.mqh"
#include "PositionTracker.mqh"
#include "EntryManager.mqh"
#include "TradeRecovery.mqh"
#include "ExitManager.mqh"

input string InpApiBaseUrl="https://YOUR-API.onrender.com";
input string InpAgentId="oracle-agent-1";
input long InpAccountId=0;
input string InpAccountToken="PASTE_ACCOUNT_TOKEN_HERE";
input string InpSymbol="AUTO";
input long InpMagic=9924102;

input bool InpAllowLiveTrading=false;
input bool InpStartEnabled=false;

input int InpPollSeconds=3;
input int InpMaxSlippagePoints=30;
input int InpMaxPositionsOverride=0;
input bool InpOneEntryPerM1Bar=false;

CTrade trade;
CSignalEngine signalEngine;
CRiskManager riskManager;
CPositionManager positionManager;
CExecutionManager executionManager;
CAdaptiveManager adaptiveManager;
CTelemetry telemetry;
CBrokerSpecification brokerSpecification;
CPositionTracker positionTracker;
CEntryManager entryManager;
CTradeRecovery tradeRecovery;
CExitManager exitManager;

bool g_enabled=false;
bool g_emergency=false;
bool g_closeAllRequested=false;
bool g_riskLocked=false;

int g_maxPositions=0;
bool g_oneEntryPerBar=false;

datetime g_lastEntryBar=0;
bool g_restartEntryBlock=false;
datetime g_lastDealSync=0;

string g_symbol="";

//+------------------------------------------------------------------+
// INITIALIZATION
//+------------------------------------------------------------------+

int OnInit()
{
   if(
      InpAccountId<=0 ||
      InpMagic<=0 ||
      StringFind(InpApiBaseUrl,"https://")!=0 ||
      StringFind(InpApiBaseUrl,"YOUR-API")>=0 ||
      InpAgentId=="" ||
      InpAccountToken=="" ||
      StringFind(InpAccountToken,"PASTE_ACCOUNT_TOKEN")>=0
   )
   {
      Print(
         "Set the API URL, account ID, account EA token ",
         "and magic number before attaching the EA."
      );
      return INIT_FAILED;
   }

   telemetry.SetToken(InpAccountToken);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePoints);
   trade.SetAsyncMode(false);

   g_symbol=ResolveGoldSymbol(InpSymbol);

   if(g_symbol=="")
   {
      Print("No supported gold symbol found. EA remains idle.");
      return INIT_FAILED;
   }

   if(!brokerSpecification.Validate(g_symbol))
   {
      Print("Broker symbol specification is invalid; EA remains idle.");
      return INIT_FAILED;
   }

   if(!trade.SetTypeFillingBySymbol(g_symbol))
   {
      Print("Broker filling mode unavailable for symbol");
      return INIT_FAILED;
   }

   executionManager.Init(g_symbol);
   adaptiveManager.Init(InpAccountId);

   g_oneEntryPerBar=InpOneEntryPerM1Bar;
   g_maxPositions=InpMaxPositionsOverride;

   datetime currentBar=iTime(g_symbol,PERIOD_M1,0);

   g_lastEntryBar=tradeRecovery.LastEntryBar(InpAccountId);

   g_restartEntryBlock=
      tradeRecovery.RestartDuplicateBlock(
         InpAccountId,
         currentBar
      );

   string riskLockKey="GoldRiskLock_"+(string)InpAccountId;
   string emergencyKey="GoldEmergency_"+(string)InpAccountId;
   string closeKey="GoldCloseAll_"+(string)InpAccountId;

   if(
      GlobalVariableCheck(riskLockKey) &&
      GlobalVariableGet(riskLockKey)>0.5
   )
      g_riskLocked=true;

   if(
      GlobalVariableCheck(emergencyKey) &&
      GlobalVariableGet(emergencyKey)>0.5
   )
      g_emergency=true;

   if(
      GlobalVariableCheck(closeKey) &&
      GlobalVariableGet(closeKey)>0.5
   )
   {
      g_closeAllRequested=true;
      g_emergency=true;
   }

   // Real accounts require explicit local authorization.
   g_enabled=
      InpStartEnabled &&
      (!IsRealAccount() || InpAllowLiveTrading);

   EventSetTimer(MathMax(1,InpPollSeconds));

   telemetry.SendEvent(
      InpApiBaseUrl,
      InpAgentId,
      InpAccountId,
      "status",
      "{\"state\":\"STARTING\",\"symbol\":\""+g_symbol+"\"}"
   );

   Print(
      "Gold Scalper initialized on ",
      g_symbol,
      "; entries enabled=",
      g_enabled,
      "; real account=",
      IsRealAccount()
   );

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
// SHUTDOWN
//+------------------------------------------------------------------+

void OnDeinit(const int reason)
{
   EventKillTimer();
   executionManager.Release();
}

//+------------------------------------------------------------------+
// TIMER
//+------------------------------------------------------------------+

void OnTimer()
{
   PollCommands();

   telemetry.Heartbeat(
      InpApiBaseUrl,
      InpAgentId,
      InpAccountId,
      g_symbol,
      g_enabled,
      InpMagic
   );

   if(TimeCurrent()-g_lastDealSync>=60)
      SyncRecentDeals();
}

//+------------------------------------------------------------------+
// MAIN TICK
//+------------------------------------------------------------------+

void OnTick()
{
   if(g_symbol=="")
      return;

   MqlTick tick;

   if(SymbolInfoTick(g_symbol,tick))
      signalEngine.Observe(tick.bid,tick.ask);

   // Manage open positions even when new entries are disabled.
   // Pass the platform account ID so original context can be loaded.
   positionManager.Manage(
      trade,
      g_symbol,
      InpMagic,
      InpAccountId,
      signalEngine
   );

   // Manual emergency close-all only.
   if(g_closeAllRequested)
   {
      exitManager.CloseAll(
         trade,
         g_symbol,
         InpMagic
      );

      if(positionTracker.Count(g_symbol,InpMagic)==0)
      {
         g_closeAllRequested=false;

         GlobalVariableSet(
            "GoldCloseAll_"+(string)InpAccountId,
            0.0
         );
      }

      return;
   }

   // Real-money trading must be explicitly authorized.
   if(IsRealAccount() && !InpAllowLiveTrading)
      return;

   // Verify terminal, EA and account trading permissions.
   if(
      !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
      !MQLInfoInteger(MQL_TRADE_ALLOWED) ||
      !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
   )
      return;

   if(!SymbolInfoTick(g_symbol,tick))
      return;

   int positions=positionTracker.Count(g_symbol,InpMagic);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);

   int allowedPositions=riskManager.MaxPositions(equity);

   if(g_maxPositions>0)
      allowedPositions=(int)MathMin(allowedPositions,g_maxPositions);

   if(
      !entryManager.CanEnter(
         positions,
         allowedPositions,
         g_enabled,
         g_emergency,
         g_riskLocked
      )
   )
      return;

   datetime currentBar=iTime(g_symbol,PERIOD_M1,0);

   if(g_restartEntryBlock)
   {
      if(currentBar==g_lastEntryBar)
         return;

      g_restartEntryBlock=false;
   }

   if(
      g_oneEntryPerBar &&
      currentBar>0 &&
      g_lastEntryBar==currentBar
   )
      return;

   // ORIGINAL ENTRY SIGNAL: unchanged.
   int confidence=0;
   ENUM_ORDER_TYPE side;

   if(!signalEngine.GetSignal(side,confidence))
      return;

   if(
      !executionManager.EntryCostOK(
         g_symbol,
         side,
         confidence
      )
   )
      return;

   // Original equity-based lot calculation.
   double volume=riskManager.VolumeForPosition(
      g_symbol,
      equity,
      positions+1
   );

   volume=riskManager.FitVolumeToMargin(
      g_symbol,
      side,
      volume,
      (side==ORDER_TYPE_BUY ? tick.ask : tick.bid),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE)
   );

   if(volume<=0.0)
      return;

   double sl=0.0;
   double tp=0.0;

   double entry=(side==ORDER_TYPE_BUY ? tick.ask : tick.bid);

   // Existing strategy conversion retained from the source EA.
   double spreadPrice=tick.ask-tick.bid;
   double goldPipSize=0.01;

   if(spreadPrice<0.0 || goldPipSize<=0.0)
      return;

   double spreadPips=spreadPrice/goldPipSize;
   double recentMovement=signalEngine.RecentMovement();
   int positionNumber=positions+1;

   if(
      !riskManager.BuildStops(
         g_symbol,
         side,
         entry,
         volume,
         confidence,
         spreadPips,
         recentMovement,
         positionNumber,
         sl,
         tp
      )
   )
   {
      Print("Dynamic SL/TP calculation failed; no order sent.");
      return;
   }

   // ORIGINAL BUY/SELL EXECUTION.
   bool ok=
      (side==ORDER_TYPE_BUY)
      ?
      trade.Buy(
         volume,
         g_symbol,
         0,
         sl,
         tp,
         "GOLD-SCALPER"
      )
      :
      trade.Sell(
         volume,
         g_symbol,
         0,
         sl,
         tp,
         "GOLD-SCALPER"
      );

   uint retcode=trade.ResultRetcode();

   bool executed=
      ok &&
      (
         retcode==TRADE_RETCODE_DONE ||
         retcode==TRADE_RETCODE_DONE_PARTIAL ||
         retcode==TRADE_RETCODE_PLACED
      );

   if(executed && currentBar>0)
   {
      tradeRecovery.RecordEntry(
         InpAccountId,
         currentBar
      );

      g_lastEntryBar=currentBar;

      // Save the broker-confirmed position's original entry context.
      SaveConfirmedEntryContext(
         trade.ResultOrder(),
         side,
         confidence
      );
   }

   telemetry.TradeResult(
      InpApiBaseUrl,
      InpAgentId,
      InpAccountId,
      g_symbol,
      side,
      volume,
      executed,
      retcode
   );
}

//+------------------------------------------------------------------+
// SAVE BROKER-CONFIRMED ORIGINAL ENTRY CONTEXT
//+------------------------------------------------------------------+

void SaveConfirmedEntryContext(
   ulong orderTicket,
   ENUM_ORDER_TYPE side,
   int confidence
)
{
   if(orderTicket==0)
      return;

   datetime now=TimeCurrent();

   if(now<=0)
      return;

   if(!HistorySelect(now-600,now+60))
   {
      Print("Cannot read recent deal history; entry context not saved.");
      return;
   }

   ulong positionIdentifier=0;
   double entryPrice=0.0;
   double initialVolume=0.0;

   int total=HistoryDealsTotal();

   for(int i=total-1;i>=0;i--)
   {
      ulong deal=HistoryDealGetTicket(i);

      if(deal==0)
         continue;

      if(HistoryDealGetInteger(deal,DEAL_ORDER)!=(long)orderTicket)
         continue;

      if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic)
         continue;

      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=g_symbol)
         continue;

      long entryType=HistoryDealGetInteger(deal,DEAL_ENTRY);

      if(entryType!=DEAL_ENTRY_IN && entryType!=DEAL_ENTRY_INOUT)
         continue;

      long dealType=HistoryDealGetInteger(deal,DEAL_TYPE);

      if(
         (side==ORDER_TYPE_BUY && dealType!=DEAL_TYPE_BUY) ||
         (side==ORDER_TYPE_SELL && dealType!=DEAL_TYPE_SELL)
      )
         continue;

      positionIdentifier=
         (ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);

      entryPrice=HistoryDealGetDouble(deal,DEAL_PRICE);
      initialVolume=HistoryDealGetDouble(deal,DEAL_VOLUME);

      if(positionIdentifier>0 && entryPrice>0.0 && initialVolume>0.0)
         break;
   }

   if(positionIdentifier==0 || entryPrice<=0.0 || initialVolume<=0.0)
   {
      Print(
         "Broker confirmed order but matching entry deal was not found. ",
         "Order=",
         orderTicket
      );
      return;
   }

   double initialSL=0.0;
   double initialTP=0.0;
   bool foundPosition=false;

   for(int p=PositionsTotal()-1;p>=0;p--)
   {
      ulong ticket=PositionGetTicket(p);

      if(ticket==0)
         continue;

      if(PositionGetInteger(POSITION_IDENTIFIER)!=(long)positionIdentifier)
         continue;

      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic)
         continue;

      if(PositionGetString(POSITION_SYMBOL)!=g_symbol)
         continue;

      initialSL=PositionGetDouble(POSITION_SL);
      initialTP=PositionGetDouble(POSITION_TP);
      foundPosition=true;
      break;
   }

   if(!foundPosition || initialSL<=0.0 || initialTP<=0.0)
   {
      Print(
         "Entry context not saved because broker position or its original ",
         "SL/TP could not be verified. Position ID=",
         positionIdentifier
      );
      return;
   }

   bool saved=tradeRecovery.SaveEntryContext(
      InpAccountId,
      positionIdentifier,
      side,
      entryPrice,
      initialSL,
      initialTP,
      initialVolume,
      confidence,
      signalEngine.GetCurrentScore(),
      signalEngine.GetShortDelta(),
      signalEngine.GetFullDelta(),
      signalEngine.GetCandleDelta(),
      signalEngine.RecentMovement(),
      signalEngine.GetCandleOpen(),
      signalEngine.GetCandleMinute(),
      now
   );

   if(saved)
   {
      Print(
         "Original entry context saved. Account=",
         InpAccountId,
         " Position ID=",
         positionIdentifier,
         " Entry=",
         DoubleToString(entryPrice,_Digits),
         " Initial SL=",
         DoubleToString(initialSL,_Digits),
         " Initial TP=",
         DoubleToString(initialTP,_Digits),
         " Initial volume=",
         DoubleToString(initialVolume,2)
      );
   }
   else
   {
      Print(
         "TradeRecovery refused to save entry context. Position ID=",
         positionIdentifier
      );
   }
}

//+------------------------------------------------------------------+
// ACCOUNT TYPE
//+------------------------------------------------------------------+

bool IsRealAccount()
{
   return
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==
      ACCOUNT_TRADE_MODE_REAL;
}

//+------------------------------------------------------------------+
// GOLD SYMBOL DETECTION
//+------------------------------------------------------------------+

string ResolveGoldSymbol(string requested)
{
   string candidates[]=
   {
      "XAUUSD",
      "XAUUSDm",
      "XAUUSDc",
      "XAUUSDr",
      "XAUUSD.a",
      "XAUUSD.ecn",
      "XAUUSD_i",
      "GOLD"
   };

   if(
      requested!="AUTO" &&
      SymbolSelect(requested,true)
   )
      return requested;

   for(int i=0;i<ArraySize(candidates);i++)
   {
      if(SymbolSelect(candidates[i],true))
         return candidates[i];
   }

   int total=SymbolsTotal(false);

   for(int i=0;i<total;i++)
   {
      string name=SymbolName(i,false);
      string upper=name;

      StringToUpper(upper);

      if(
         StringFind(upper,"XAUUSD")>=0 ||
         StringFind(upper,"GOLD")>=0
      )
      {
         if(SymbolSelect(name,true))
            return name;
      }
   }

   return "";
}

//+------------------------------------------------------------------+
// JSON HELPERS
//+------------------------------------------------------------------+

string JsonStringValue(string json,string key)
{
   string needle="\""+key+"\":";
   int search=0;

   while(search<StringLen(json))
   {
      int p=StringFind(json,needle,search);

      if(p<0)
         return "";

      p+=StringLen(needle);

      while(
         p<StringLen(json) &&
         StringGetCharacter(json,p)==' '
      )
         p++;

      if(
         p<StringLen(json) &&
         StringGetCharacter(json,p)=='\"'
      )
      {
         p++;
         int e=StringFind(json,"\"",p);

         if(e<0)
            return "";

         return StringSubstr(json,p,e-p);
      }

      search=p+1;
   }

   return "";
}

long JsonLongValue(string json,string key)
{
   string needle="\""+key+"\":";
   int p=StringFind(json,needle);

   if(p<0)
      return 0;

   p+=StringLen(needle);

   while(
      p<StringLen(json) &&
      StringGetCharacter(json,p)==' '
   )
      p++;

   int e=p;

   while(e<StringLen(json))
   {
      ushort c=StringGetCharacter(json,e);

      if(c<'0' || c>'9')
         break;

      e++;
   }

   return (long)StringToInteger(
      StringSubstr(json,p,e-p)
   );
}

double JsonDoubleValue(
   string json,
   string key,
   double fallback
)
{
   string needle="\""+key+"\":";
   int p=StringFind(json,needle);

   if(p<0)
      return fallback;

   p+=StringLen(needle);

   while(
      p<StringLen(json) &&
      StringGetCharacter(json,p)==' '
   )
      p++;

   int e=p;

   while(e<StringLen(json))
   {
      ushort c=StringGetCharacter(json,e);

      if(
         (c<'0' || c>'9') &&
         c!='.' &&
         c!='-'
      )
         break;

      e++;
   }

   if(e<=p)
      return fallback;

   return StringToDouble(
      StringSubstr(json,p,e-p)
   );
}

bool JsonBoolValue(
   string json,
   string key,
   bool fallback
)
{
   string needle="\""+key+"\":";
   int p=StringFind(json,needle);

   if(p<0)
      return fallback;

   p+=StringLen(needle);

   while(
      p<StringLen(json) &&
      StringGetCharacter(json,p)==' '
   )
      p++;

   if(StringSubstr(json,p,4)=="true")
      return true;

   if(StringSubstr(json,p,5)=="false")
      return false;

   return fallback;
}

//+------------------------------------------------------------------+
// BACKEND COMMANDS
//+------------------------------------------------------------------+

void PollCommands()
{
   string response="";

   if(
      telemetry.Get(
         InpApiBaseUrl+
         "/api/ea/next?account_id="+
         (string)InpAccountId,
         response
      )
   )
   {
      long commandId=JsonLongValue(response,"id");
      string commandName=JsonStringValue(response,"command");

      bool applied=false;
      string result="{\"applied\":true}";

      if(commandName=="CLOSE_ALL")
      {
         g_enabled=false;
         g_emergency=true;
         g_closeAllRequested=true;

         GlobalVariableSet(
            "GoldEmergency_"+(string)InpAccountId,
            1.0
         );

         GlobalVariableSet(
            "GoldCloseAll_"+(string)InpAccountId,
            1.0
         );

         result="{\"requested\":true,\"new_entries_disabled\":true}";
         applied=true;
      }
      else if(commandName=="START")
      {
         if(!g_riskLocked)
         {
            g_emergency=false;

            GlobalVariableSet(
               "GoldEmergency_"+(string)InpAccountId,
               0.0
            );
         }

         applied=true;
      }
      else if(commandName=="STOP")
      {
         g_enabled=false;
         applied=true;
      }
      else if(commandName=="EMERGENCY_STOP")
      {
         g_emergency=true;
         g_enabled=false;

         GlobalVariableSet(
            "GoldEmergency_"+(string)InpAccountId,
            1.0
         );

         applied=true;
      }
      else if(commandName=="RISK_RESET")
      {
         g_riskLocked=false;

         GlobalVariableSet(
            "GoldRiskLock_"+(string)InpAccountId,
            0.0
         );

         applied=true;
      }
      else if(commandName=="SETTINGS")
      {
         g_maxPositions=
            (int)JsonLongValue(response,"max_positions");

         g_oneEntryPerBar=JsonBoolValue(
            response,
            "one_entry_per_m1_bar",
            g_oneEntryPerBar
         );

         applied=true;
      }

      if(commandId>0 && applied)
      {
         telemetry.Ack(
            InpApiBaseUrl,
            InpAccountId,
            commandId,
            result
         );
      }
   }

   string permission="";

   if(
      telemetry.Get(
         InpApiBaseUrl+
         "/api/ea/permission?account_id="+
         (string)InpAccountId,
         permission
      )
   )
   {
      g_enabled=
         (StringFind(
            permission,
            "\"entries_allowed\":true"
         )>=0) &&
         !g_riskLocked &&
         !g_emergency;
   }
   else
   {
      // Fail closed for new entries.
      // Existing positions continue to be managed.
      g_enabled=false;
   }
}

//+------------------------------------------------------------------+
// RECENT DEAL SYNCHRONIZATION
//+------------------------------------------------------------------+

void SyncRecentDeals()
{
   datetime now=TimeCurrent();

   if(now<=0)
      return;

   if(!HistorySelect(now-30*86400,now))
      return;

   int total=HistoryDealsTotal();
   int first=MathMax(0,total-1000);

   string deals="[";
   int added=0;

   for(int i=first;i<total;i++)
   {
      ulong deal=HistoryDealGetTicket(i);

      if(deal==0 || !HistoryDealSelect(deal))
         continue;

      if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic)
         continue;

      long entryType=HistoryDealGetInteger(deal,DEAL_ENTRY);

      double dealPnl=
         HistoryDealGetDouble(deal,DEAL_PROFIT)+
         HistoryDealGetDouble(deal,DEAL_COMMISSION)+
         HistoryDealGetDouble(deal,DEAL_SWAP);

      if(
         entryType==DEAL_ENTRY_OUT ||
         entryType==DEAL_ENTRY_OUT_BY ||
         entryType==DEAL_ENTRY_INOUT
      )
      {
         adaptiveManager.RecordOutcome(
            InpAccountId,
            deal,
            dealPnl
         );
      }

      string symbol=HistoryDealGetString(deal,DEAL_SYMBOL);
      string side="OTHER";

      long type=HistoryDealGetInteger(deal,DEAL_TYPE);

      if(type==DEAL_TYPE_BUY)
         side="BUY";
      else if(type==DEAL_TYPE_SELL)
         side="SELL";

      double profit=
         HistoryDealGetDouble(deal,DEAL_PROFIT)+
         HistoryDealGetDouble(deal,DEAL_COMMISSION)+
         HistoryDealGetDouble(deal,DEAL_SWAP);

      if(added>0)
         deals+=",";

      deals+=
         "{\"deal_id\":\""+(string)deal+
         "\",\"magic\":"+(string)InpMagic+
         ",\"symbol\":\""+symbol+
         "\",\"side\":\""+side+
         "\",\"volume\":"+
         DoubleToString(
            HistoryDealGetDouble(deal,DEAL_VOLUME),
            2
         )+
         ",\"profit\":"+
         DoubleToString(profit,2)+
         ",\"entry\":"+
         (string)HistoryDealGetInteger(deal,DEAL_ENTRY)+
         ",\"time\":"+
         (string)HistoryDealGetInteger(deal,DEAL_TIME)+
         "}";

      added++;
   }

   deals+="]";

   if(added>0)
   {
      telemetry.DealsBatch(
         InpApiBaseUrl,
         InpAccountId,
         deals
      );
   }

   g_lastDealSync=now;
}
