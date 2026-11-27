
#property strict
#property version "1.01"
#property description "Gold Scalper EA - individual position management; demo-first"

#include <Trade/Trade.mqh>

#include "SignalEngine.mqh"
#include "RiskManager.mqh"
#include "PositionManager.mqh"
#include "ExecutionManager.mqh"
#include "AdaptiveManager.mqh"
#include "Telemetry.mqh"
#include "NewsFilter.mqh"
#include "SessionFilter.mqh"
#include "SignalConfirmation.mqh"
#include "EntryFilter.mqh"
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

input bool InpNewsFilterEnabled=false;
input int InpNewsMinutesBefore=15;
input int InpNewsMinutesAfter=15;

input bool InpSessionFilterEnabled=false;
input int InpSessionStartHour=0;
input int InpSessionEndHour=24;

input bool InpRequireCandleConfirmation=true;

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
CNewsFilter newsFilter;
CSessionFilter sessionFilter;
CEntryFilter entryFilter;

bool g_enabled=false;
bool g_emergency=false;
bool g_closeAllRequested=false;
bool g_riskLocked=false;

int g_maxPositions=0;

bool g_oneEntryPerBar=false;
bool g_newsFilterEnabled=false;
bool g_sessionFilterEnabled=false;
bool g_requireCandleConfirmation=true;

int g_newsMinutesBefore=15;
int g_newsMinutesAfter=15;

int g_sessionStartHour=0;
int g_sessionEndHour=24;

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
      Print(
         "Broker symbol specification is invalid; ",
         "EA remains idle."
      );

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

   g_newsFilterEnabled=InpNewsFilterEnabled;
   g_newsMinutesBefore=InpNewsMinutesBefore;
   g_newsMinutesAfter=InpNewsMinutesAfter;

   g_sessionFilterEnabled=InpSessionFilterEnabled;
   g_sessionStartHour=InpSessionStartHour;
   g_sessionEndHour=InpSessionEndHour;

   g_requireCandleConfirmation=InpRequireCandleConfirmation;

   datetime currentBar=iTime(g_symbol,PERIOD_M1,0);

   g_lastEntryBar=tradeRecovery.LastEntryBar(InpAccountId);

   g_restartEntryBlock=
      tradeRecovery.RestartDuplicateBlock(
         InpAccountId,
         currentBar
      );

   string riskLockKey=
      "GoldRiskLock_"+(string)InpAccountId;

   string emergencyKey=
      "GoldEmergency_"+(string)InpAccountId;

   if(
      GlobalVariableCheck(riskLockKey) &&
      GlobalVariableGet(riskLockKey)>0.5
   )
   {
      g_riskLocked=true;
   }

   if(
      GlobalVariableCheck(emergencyKey) &&
      GlobalVariableGet(emergencyKey)>0.5
   )
   {
      g_emergency=true;
   }

   string closeKey=
      "GoldCloseAll_"+(string)InpAccountId;

   if(
      GlobalVariableCheck(closeKey) &&
      GlobalVariableGet(closeKey)>0.5
   )
   {
      g_closeAllRequested=true;
      g_emergency=true;
   }

   // Live trading remains disabled unless explicitly permitted.
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
      g_enabled
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

   // Record the newest available price BEFORE position management.
   // This gives the supervisor the freshest momentum information.
   MqlTick tick;

   if(SymbolInfoTick(g_symbol,tick))
   {
      signalEngine.Observe(tick.bid,tick.ask);
   }

   // Existing positions are always managed independently.
   // This continues even when new entries are disabled.
   positionManager.Manage(
      trade,
      g_symbol,
      InpMagic,
      signalEngine
   );

   // A manual emergency CLOSE_ALL command remains supported.
   // This is not an automatic basket-profit or basket-loss rule.
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

   // Do not open new positions on a real account unless
   // live trading was explicitly enabled.
   if(IsRealAccount() && !InpAllowLiveTrading)
      return;

   if(!SymbolInfoTick(g_symbol,tick))
      return;

   int positions=
      positionTracker.Count(g_symbol,InpMagic);

   double equity=
      AccountInfoDouble(ACCOUNT_EQUITY);

   // Position management has already run above.
   // No fixed account drawdown or basket-loss close-all
   // is performed here.

   int allowedPositions=
      riskManager.MaxPositions(equity);

   if(g_maxPositions>0)
   {
      allowedPositions=
         MathMin(allowedPositions,g_maxPositions);
   }

   if(
      !entryManager.CanEnter(
         positions,
         allowedPositions,
         g_enabled,
         g_emergency,
         g_riskLocked
      )
   )
   {
      return;
   }

   datetime currentBar=
      iTime(g_symbol,PERIOD_M1,0);

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
   {
      return;
   }

   // Original entry signal calculation is preserved.
   int confidence=0;
   ENUM_ORDER_TYPE side;

   if(!signalEngine.GetSignal(side,confidence))
      return;

   if(confidence<adaptiveManager.MinimumConfidence())
      return;

   if(
      !entryFilter.Allowed(
         g_symbol,
         side,
         g_requireCandleConfirmation
      )
   )
   {
      return;
   }

   if(
      !sessionFilter.Allowed(
         g_sessionFilterEnabled,
         g_sessionStartHour,
         g_sessionEndHour
      )
   )
   {
      return;
   }

   if(
      newsFilter.IsBlocked(
         g_newsFilterEnabled,
         "USD",
         g_newsMinutesBefore,
         g_newsMinutesAfter
      )
   )
   {
      return;
   }

   if(
      !executionManager.EntryCostOK(
         g_symbol,
         side,
         confidence
      )
   )
   {
      return;
   }

   // Original equity-based volume calculation.
   double volume=
      riskManager.VolumeForPosition(
         g_symbol,
         equity,
         positions+1
      );

   volume=
      riskManager.NormalizeVolume(
         g_symbol,
         volume*adaptiveManager.VolumeMultiplier()
      );

   // Check actual broker margin requirements.
   volume=
      riskManager.FitVolumeToMargin(
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

   double entry=
      (side==ORDER_TYPE_BUY ? tick.ask : tick.bid);

   if(
      !riskManager.BuildStops(
         g_symbol,
         side,
         entry,
         volume,
         confidence,
         sl,
         tp
      )
   )
   {
      return;
   }

   // Original BUY/SELL execution.
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
   {
      return requested;
   }

   for(int i=0;i<ArraySize(candidates);i++)
   {
      if(SymbolSelect(candidates[i],true))
         return candidates[i];
   }

   // Discover broker prefix/suffix variants.
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
      {
         p++;
      }

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
   {
      p++;
   }

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
   {
      p++;
   }

   int e=p;

   while(e<StringLen(json))
   {
      ushort c=StringGetCharacter(json,e);

      if(
         (c<'0' || c>'9') &&
         c!='.' &&
         c!='-'
      )
      {
         break;
      }

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
   {
      p++;
   }

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
      long commandId=
         JsonLongValue(response,"id");

      string commandName=
         JsonStringValue(response,"command");

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

         result=
            "{\"requested\":true,\"new_entries_disabled\":true}";

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

         g_newsMinutesBefore=
            (int)JsonLongValue(response,"news_minutes_before");

         g_newsMinutesAfter=
            (int)JsonLongValue(response,"news_minutes_after");

         g_sessionStartHour=
            (int)JsonLongValue(response,"session_start_hour");

         g_sessionEndHour=
            (int)JsonLongValue(response,"session_end_hour");

         g_oneEntryPerBar=
            JsonBoolValue(
               response,
               "one_entry_per_m1_bar",
               g_oneEntryPerBar
            );

         g_newsFilterEnabled=
            JsonBoolValue(
               response,
               "news_filter_enabled",
               g_newsFilterEnabled
            );

         g_sessionFilterEnabled=
            JsonBoolValue(
               response,
               "session_filter_enabled",
               g_sessionFilterEnabled
            );

         g_requireCandleConfirmation=
            JsonBoolValue(
               response,
               "require_candle_confirmation",
               g_requireCandleConfirmation
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

      if(
         HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic
      )
      {
         continue;
      }

      long entryType=
         HistoryDealGetInteger(deal,DEAL_ENTRY);

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

      string symbol=
         HistoryDealGetString(deal,DEAL_SYMBOL);

      string side="OTHER";

      long type=
         HistoryDealGetInteger(deal,DEAL_TYPE);

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
