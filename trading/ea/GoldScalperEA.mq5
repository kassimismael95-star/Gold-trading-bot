
#property strict
#property version "1.06"
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

//+------------------------------------------------------------------+
// ACCOUNT CONFIGURATION
// Attach one EA instance to each separate MT5 account terminal.
//+------------------------------------------------------------------+

input string InpApiBaseUrl="https://YOUR-API.onrender.com";
input string InpAgentId="oracle-agent-1";
input long InpAccountId=0;
input string InpAccountToken="PASTE_ACCOUNT_TOKEN_HERE";

input string InpSymbol="AUTO";
input long InpMagic=9924102;

input ENUM_ACCOUNT_TRADE_MODE InpRequiredAccountMode=ACCOUNT_TRADE_MODE_DEMO;

input bool InpAllowLiveTrading=false;
input bool InpConfirmRealMoneyTrading=false;

input bool InpStartEnabled=false;

input int InpPollSeconds=3;
input int InpMaxSlippagePoints=30;
input int InpMaxPositionsOverride=0;
input bool InpOneEntryPerM1Bar=false;

//+------------------------------------------------------------------+
// OBJECTS
//+------------------------------------------------------------------+

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

//+------------------------------------------------------------------+
// STATE
//+------------------------------------------------------------------+

bool g_enabled=false;
bool g_startRequested=false;

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
// ACCOUNT HELPERS
//+------------------------------------------------------------------+

bool IsRealAccount()
{
   return AccountInfoInteger(ACCOUNT_TRADE_MODE)==
          ACCOUNT_TRADE_MODE_REAL;
}

bool IsDemoAccount()
{
   return AccountInfoInteger(ACCOUNT_TRADE_MODE)==
          ACCOUNT_TRADE_MODE_DEMO;
}

string AccountModeName()
{
   if(IsRealAccount())
      return "REAL";

   if(IsDemoAccount())
      return "DEMO";

   return "OTHER";
}

bool LocalEntryAuthorization()
{
   ENUM_ACCOUNT_TRADE_MODE actualMode=
      (ENUM_ACCOUNT_TRADE_MODE)
      AccountInfoInteger(ACCOUNT_TRADE_MODE);

   if(actualMode!=InpRequiredAccountMode)
      return false;

   if(actualMode==ACCOUNT_TRADE_MODE_REAL)
   {
      if(!InpAllowLiveTrading)
         return false;

      if(!InpConfirmRealMoneyTrading)
         return false;
   }

   if(
      actualMode!=ACCOUNT_TRADE_MODE_REAL &&
      actualMode!=ACCOUNT_TRADE_MODE_DEMO
   )
      return false;

   return true;
}

// Recalculate effective permission without changing START intent.
void RefreshEntryPermission(bool backendAllowed)
{
   g_enabled=
      g_startRequested &&
      backendAllowed &&
      LocalEntryAuthorization() &&
      !g_riskLocked &&
      !g_emergency &&
      !g_closeAllRequested;
}

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
         "Configure API URL, account ID, account token ",
         "and magic number before attaching the EA."
      );

      return INIT_FAILED;
   }

   ENUM_ACCOUNT_TRADE_MODE actualMode=
      (ENUM_ACCOUNT_TRADE_MODE)
      AccountInfoInteger(ACCOUNT_TRADE_MODE);

   if(actualMode!=InpRequiredAccountMode)
   {
      Print(
         "ACCOUNT MODE MISMATCH. Required=",
         (int)InpRequiredAccountMode,
         " Actual=",
         (int)actualMode
      );

      return INIT_FAILED;
   }

   if(
      actualMode!=ACCOUNT_TRADE_MODE_REAL &&
      actualMode!=ACCOUNT_TRADE_MODE_DEMO
   )
   {
      Print("Unsupported MT5 account mode.");
      return INIT_FAILED;
   }

   telemetry.SetToken(InpAccountToken);

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpMaxSlippagePoints);
   trade.SetAsyncMode(false);

   g_symbol=ResolveGoldSymbol(InpSymbol);

   if(g_symbol=="")
   {
      Print("No valid gold symbol found.");
      return INIT_FAILED;
   }

   if(!brokerSpecification.Validate(g_symbol))
   {
      Print("Broker symbol specification is invalid.");
      return INIT_FAILED;
   }

   if(!trade.SetTypeFillingBySymbol(g_symbol))
   {
      Print("Broker filling mode unavailable.");
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

   // Never assume a previous START request survived a restart.
   g_startRequested=InpStartEnabled;

   g_enabled=
      g_startRequested &&
      LocalEntryAuthorization() &&
      !g_riskLocked &&
      !g_emergency &&
      !g_closeAllRequested;

   int timerSeconds=(int)MathMax(1,InpPollSeconds);

   if(!EventSetTimer(timerSeconds))
   {
      Print("Failed to start EA management timer.");
      return INIT_FAILED;
   }

   telemetry.SendEvent(
      InpApiBaseUrl,
      InpAgentId,
      InpAccountId,
      "status",
      "{\"state\":\"STARTING\",\"symbol\":\""+g_symbol+
      "\",\"account_mode\":\""+AccountModeName()+"\"}"
   );

   Print(
      "Gold Scalper initialized.",
      " Symbol=",g_symbol,
      " Account ID=",InpAccountId,
      " Account mode=",AccountModeName(),
      " Start requested=",g_startRequested,
      " Entries enabled=",g_enabled
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

   // Continue managing existing positions even when entries stop.
   if(g_symbol!="")
   {
      positionManager.Manage(
         trade,
         g_symbol,
         InpMagic,
         InpAccountId,
         signalEngine
      );
   }

   if(g_closeAllRequested && g_symbol!="")
   {
      exitManager.CloseAll(
         trade,
         g_symbol,
         InpMagic
      );

      if(positionTracker.Count(g_symbol,InpMagic)==0)
      {
         g_closeAllRequested=false;
         g_startRequested=false;
         g_enabled=false;

         GlobalVariableSet(
            "GoldCloseAll_"+(string)InpAccountId,
            0.0
         );

         Print("Close-all completed.");
      }
   }

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
// MAIN TICK: ORIGINAL ENTRY STRATEGY
//+------------------------------------------------------------------+

void OnTick()
{
   if(g_symbol=="")
      return;

   MqlTick tick;

   if(!SymbolInfoTick(g_symbol,tick))
      return;

   signalEngine.Observe(tick.bid,tick.ask);

   if(!g_enabled)
      return;

   if(g_closeAllRequested || g_emergency || g_riskLocked)
      return;

   if(!LocalEntryAuthorization())
      return;

   if(
      !TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ||
      !MQLInfoInteger(MQL_TRADE_ALLOWED) ||
      !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
   )
      return;

   int positions=positionTracker.Count(g_symbol,InpMagic);

   double equity=AccountInfoDouble(ACCOUNT_EQUITY);

   int allowedPositions=riskManager.MaxPositions(equity);

   if(g_maxPositions>0)
      allowedPositions=
         (int)MathMin(allowedPositions,g_maxPositions);

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

   int confidence=0;
   ENUM_ORDER_TYPE side;

   if(!signalEngine.GetSignal(side,confidence))
      return;

   if(!brokerSpecification.AllowsDirection(side))
      return;

   if(
      !executionManager.EntryCostOK(
         g_symbol,
         side,
         confidence
      )
   )
      return;

   double volume=riskManager.VolumeForPosition(
      g_symbol,
      equity,
      positions+1
   );

   double entry=
      (side==ORDER_TYPE_BUY ? tick.ask : tick.bid);

   volume=riskManager.FitVolumeToMargin(
      g_symbol,
      side,
      volume,
      entry,
      AccountInfoDouble(ACCOUNT_MARGIN_FREE)
   );

   if(volume<=0.0)
      return;

   double sl=0.0;
   double tp=0.0;

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

   ulong orderTicket=trade.ResultOrder();
   ulong dealTicket=trade.ResultDeal();

   bool acceptedFill=
      ok &&
      (
         retcode==TRADE_RETCODE_DONE ||
         retcode==TRADE_RETCODE_DONE_PARTIAL
      );

   bool confirmedFill=false;

   if(acceptedFill)
   {
      confirmedFill=EntryDealExists(
         orderTicket,
         dealTicket,
         side
      );
   }

   if(confirmedFill)
   {
      if(currentBar>0)
      {
         tradeRecovery.RecordEntry(
            InpAccountId,
            currentBar
         );

         g_lastEntryBar=currentBar;
      }

      SaveConfirmedEntryContext(
         orderTicket,
         dealTicket,
         side,
         confidence
      );
   }
   else if(retcode==TRADE_RETCODE_PLACED)
   {
      Print(
         "Order accepted but fill not yet confirmed. Order=",
         orderTicket
      );
   }
   else if(ok)
   {
      Print(
         "Trade request returned without confirmed matching deal. ",
         "Retcode=",retcode
      );
   }

   telemetry.TradeResult(
      InpApiBaseUrl,
      InpAgentId,
      InpAccountId,
      g_symbol,
      side,
      volume,
      confirmedFill,
      retcode
   );
}

//+------------------------------------------------------------------+
// CONFIRM ENTRY DEAL
//+------------------------------------------------------------------+

bool EntryDealExists(
   ulong orderTicket,
   ulong dealTicket,
   ENUM_ORDER_TYPE side
)
{
   datetime now=TimeCurrent();

   if(now<=0 || !HistorySelect(now-600,now+60))
      return false;

   if(dealTicket>0)
   {
      bool orderMatches=
         orderTicket==0 ||
         HistoryDealGetInteger(dealTicket,DEAL_ORDER)==
         (long)orderTicket;

      if(
         orderMatches &&
         HistoryDealGetInteger(dealTicket,DEAL_MAGIC)==InpMagic &&
         HistoryDealGetString(dealTicket,DEAL_SYMBOL)==g_symbol
      )
      {
         long entryType=
            HistoryDealGetInteger(dealTicket,DEAL_ENTRY);

         long dealType=
            HistoryDealGetInteger(dealTicket,DEAL_TYPE);

         bool correctEntry=
            entryType==DEAL_ENTRY_IN ||
            entryType==DEAL_ENTRY_INOUT;

         bool correctSide=
            (side==ORDER_TYPE_BUY && dealType==DEAL_TYPE_BUY) ||
            (side==ORDER_TYPE_SELL && dealType==DEAL_TYPE_SELL);

         if(correctEntry && correctSide)
            return true;
      }
   }

   if(orderTicket==0)
      return false;

   for(int i=HistoryDealsTotal()-1;i>=0;i--)
   {
      ulong deal=HistoryDealGetTicket(i);

      if(deal==0)
         continue;

      if(
         HistoryDealGetInteger(deal,DEAL_ORDER)!=
         (long)orderTicket
      )
         continue;

      if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic)
         continue;

      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=g_symbol)
         continue;

      long entryType=
         HistoryDealGetInteger(deal,DEAL_ENTRY);

      long dealType=
         HistoryDealGetInteger(deal,DEAL_TYPE);

      if(
         entryType!=DEAL_ENTRY_IN &&
         entryType!=DEAL_ENTRY_INOUT
      )
         continue;

      if(
         side==ORDER_TYPE_BUY &&
         dealType!=DEAL_TYPE_BUY
      )
         continue;

      if(
         side==ORDER_TYPE_SELL &&
         dealType!=DEAL_TYPE_SELL
      )
         continue;

      if(
         HistoryDealGetDouble(deal,DEAL_VOLUME)>0.0 &&
         HistoryDealGetDouble(deal,DEAL_PRICE)>0.0
      )
         return true;
   }

   return false;
}

//+------------------------------------------------------------------+
// SAVE BROKER-CONFIRMED ENTRY CONTEXT
//+------------------------------------------------------------------+

bool SaveConfirmedEntryContext(
   ulong orderTicket,
   ulong dealTicket,
   ENUM_ORDER_TYPE side,
   int confidence
)
{
   datetime now=TimeCurrent();

   if(now<=0 || !HistorySelect(now-600,now+60))
   {
      Print("Cannot read recent deal history.");
      return false;
   }

   ulong positionIds[];
   double totalVolumes[];
   double weightedPrices[];

   ArrayResize(positionIds,0);
   ArrayResize(totalVolumes,0);
   ArrayResize(weightedPrices,0);

   int total=HistoryDealsTotal();

   for(int i=0;i<total;i++)
   {
      ulong deal=HistoryDealGetTicket(i);

      if(deal==0)
         continue;

      if(orderTicket>0)
      {
         if(
            HistoryDealGetInteger(deal,DEAL_ORDER)!=
            (long)orderTicket
         )
            continue;
      }
      else if(deal!=dealTicket)
      {
         continue;
      }

      if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic)
         continue;

      if(HistoryDealGetString(deal,DEAL_SYMBOL)!=g_symbol)
         continue;

      long entryType=
         HistoryDealGetInteger(deal,DEAL_ENTRY);

      if(
         entryType!=DEAL_ENTRY_IN &&
         entryType!=DEAL_ENTRY_INOUT
      )
         continue;

      long dealType=
         HistoryDealGetInteger(deal,DEAL_TYPE);

      if(
         side==ORDER_TYPE_BUY &&
         dealType!=DEAL_TYPE_BUY
      )
         continue;

      if(
         side==ORDER_TYPE_SELL &&
         dealType!=DEAL_TYPE_SELL
      )
         continue;

      ulong positionId=
         (ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);

      double fillVolume=
         HistoryDealGetDouble(deal,DEAL_VOLUME);

      double fillPrice=
         HistoryDealGetDouble(deal,DEAL_PRICE);

      if(
         positionId==0 ||
         fillVolume<=0.0 ||
         fillPrice<=0.0
      )
         continue;

      int index=-1;

      for(int j=0;j<ArraySize(positionIds);j++)
      {
         if(positionIds[j]==positionId)
         {
            index=j;
            break;
         }
      }

      if(index<0)
      {
         index=ArraySize(positionIds);

         ArrayResize(positionIds,index+1);
         ArrayResize(totalVolumes,index+1);
         ArrayResize(weightedPrices,index+1);

         positionIds[index]=positionId;
         totalVolumes[index]=0.0;
         weightedPrices[index]=0.0;
      }

      totalVolumes[index]+=fillVolume;
      weightedPrices[index]+=(fillPrice*fillVolume);
   }

   if(ArraySize(positionIds)==0)
   {
      Print("No matching broker entry deals found.");
      return false;
   }

   bool anyContextSaved=false;

   for(int n=0;n<ArraySize(positionIds);n++)
   {
      ulong positionId=positionIds[n];

      double fillVolume=totalVolumes[n];

      if(fillVolume<=0.0)
         continue;

      double averageEntry=weightedPrices[n]/fillVolume;

      if(
         tradeRecovery.HasEntryContext(
            InpAccountId,
            positionId
         )
      )
      {
         anyContextSaved=true;
         continue;
      }

      double initialSL=0.0;
      double initialTP=0.0;
      double currentPositionVolume=0.0;
      bool foundPosition=false;

      for(int p=PositionsTotal()-1;p>=0;p--)
      {
         ulong ticket=PositionGetTicket(p);

         if(ticket==0)
            continue;

         if(
            (ulong)PositionGetInteger(POSITION_IDENTIFIER)!=
            positionId
         )
            continue;

         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic)
            continue;

         if(PositionGetString(POSITION_SYMBOL)!=g_symbol)
            continue;

         long positionType=PositionGetInteger(POSITION_TYPE);

         if(
            side==ORDER_TYPE_BUY &&
            positionType!=POSITION_TYPE_BUY
         )
            continue;

         if(
            side==ORDER_TYPE_SELL &&
            positionType!=POSITION_TYPE_SELL
         )
            continue;

         initialSL=PositionGetDouble(POSITION_SL);
         initialTP=PositionGetDouble(POSITION_TP);

         currentPositionVolume=
            PositionGetDouble(POSITION_VOLUME);

         foundPosition=true;
         break;
      }

      if(!foundPosition)
      {
         Print("Position not found after confirmed fill. ID=",positionId);
         continue;
      }

      double volumeTolerance=
         MathMax(
            SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_STEP)*0.5,
            0.00000001
         );

      // Conservative netting handling:
      // do not fabricate original context for a merged position.
      if(
         MathAbs(currentPositionVolume-fillVolume)>
         volumeTolerance
      )
      {
         Print(
            "Context not saved: net position volume differs ",
            "from confirmed fills. Position ID=",positionId
         );

         continue;
      }

      if(initialSL<=0.0 || initialTP<=0.0)
      {
         Print(
            "Context not saved: initial broker SL/TP unavailable. ID=",
            positionId
         );

         continue;
      }

      bool saved=tradeRecovery.SaveEntryContext(
         InpAccountId,
         positionId,
         side,
         averageEntry,
         initialSL,
         initialTP,
         fillVolume,
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
         anyContextSaved=true;

         Print(
            "Entry context saved. Account=",InpAccountId,
            " Position ID=",positionId,
            " Entry=",DoubleToString(averageEntry,_Digits),
            " SL=",DoubleToString(initialSL,_Digits),
            " TP=",DoubleToString(initialTP,_Digits),
            " Volume=",DoubleToString(fillVolume,2)
         );
      }
   }

   return anyContextSaved;
}

//+------------------------------------------------------------------+
// GOLD SYMBOL DETECTION
//+------------------------------------------------------------------+

string ResolveGoldSymbol(string requested)
{
   if(requested!="AUTO")
   {
      if(!SymbolSelect(requested,true))
      {
         Print("Requested symbol unavailable: ",requested);
         return "";
      }

      return requested;
   }

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

   if(
      e<StringLen(json) &&
      StringGetCharacter(json,e)=='-'
   )
      e++;

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
         c!='-' &&
         c!='e' &&
         c!='E' &&
         c!='+'
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

      string commandName=
         JsonStringValue(response,"command");

      bool applied=false;

      string result="{\"applied\":true}";

      if(commandName=="CLOSE_ALL")
      {
         g_startRequested=false;
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
         if(
            LocalEntryAuthorization() &&
            !g_riskLocked &&
            !g_closeAllRequested &&
            !g_emergency
         )
         {
            g_startRequested=true;

            result=
               "{\"accepted\":true,\"start_requested\":true}";
         }
         else
         {
            g_startRequested=false;
            g_enabled=false;

            result=
               "{\"accepted\":false,\"reason\":\"local_authorization_or_safety_lock\"}";
         }

         applied=true;
      }
      else if(commandName=="STOP")
      {
         g_startRequested=false;
         g_enabled=false;

         result=
            "{\"stopped\":true,\"new_entries_disabled\":true,\"existing_positions_still_managed\":true}";

         applied=true;
      }
      else if(commandName=="EMERGENCY_STOP")
      {
         g_startRequested=false;
         g_emergency=true;
         g_enabled=false;

         GlobalVariableSet(
            "GoldEmergency_"+(string)InpAccountId,
            1.0
         );

         result=
            "{\"emergency_stop\":true,\"new_entries_disabled\":true,\"existing_positions_still_managed\":true}";

         applied=true;
      }
      else if(commandName=="RISK_RESET")
      {
         // CRITICAL FIX:
         // Clear the previous START request as well as the risk lock.
         // This prevents the permission refresh below from re-enabling
         // entries using an old START request.
         g_startRequested=false;

         g_riskLocked=false;

         GlobalVariableSet(
            "GoldRiskLock_"+(string)InpAccountId,
            0.0
         );

         // Effective entry permission remains disabled.
         g_enabled=false;

         result=
            "{\"risk_lock_cleared\":true,\"start_required\":true,\"entries_enabled\":false}";

         applied=true;

         Print(
            "RISK_RESET received. Risk lock cleared. ",
            "Previous START request cleared. ",
            "A separate START command is required."
         );
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

   // Backend authorization is required for both account modes.
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
      bool backendAllowed=
         JsonBoolValue(
            permission,
            "entries_allowed",
            false
         );

      RefreshEntryPermission(backendAllowed);
   }
   else
   {
      // Fail closed. Do not erase explicit START intent on outage.
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
   int first=(int)MathMax(0,total-1000);

   string deals="[";
   int added=0;

   for(int i=first;i<total;i++)
   {
      ulong deal=HistoryDealGetTicket(i);

      if(deal==0)
         continue;

      if(HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagic)
         continue;

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
         (string)entryType+
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
