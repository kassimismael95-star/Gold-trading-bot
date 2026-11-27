
#property strict
#property version "1.04"
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

// The required mode prevents accidentally attaching the real
// configuration to a demo terminal, or vice versa.
input ENUM_ACCOUNT_TRADE_MODE InpRequiredAccountMode=ACCOUNT_TRADE_MODE_DEMO;

// Both switches must be true for real-money trading.
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
   return
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==
      ACCOUNT_TRADE_MODE_REAL;
}

bool IsDemoAccount()
{
   return
      AccountInfoInteger(ACCOUNT_TRADE_MODE)==
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

// Local permission is independent of backend permission.
// The backend must authorize the account as well.
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
         "Configure the API URL, account ID, account token ",
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
         (int)actualMode,
         ". EA will not initialize on the wrong account."
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
      Print("Broker filling mode unavailable for symbol.");
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

   string riskLockKey=
      "GoldRiskLock_"+(string)InpAccountId;

   string emergencyKey=
      "GoldEmergency_"+(string)InpAccountId;

   string closeKey=
      "GoldCloseAll_"+(string)InpAccountId;

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

   g_enabled=
      InpStartEnabled &&
      LocalEntryAuthorization();

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
      " Local live authorization=",
      (IsRealAccount() ? LocalEntryAuthorization() : false),
      " Entries enabled=",g_enabled
   );

   if(IsRealAccount() && !LocalEntryAuthorization())
   {
      Print(
         "REAL ACCOUNT DETECTED: entries remain disabled until ",
         "both live authorization inputs and backend permission are enabled."
      );
   }

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
// TIMER: MANAGEMENT, COMMANDS AND HEARTBEAT
//+------------------------------------------------------------------+

void OnTimer()
{
   // Backend commands and account permission.
   PollCommands();

   // Existing positions remain managed even when entries are stopped.
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

   // Manual close-all is handled on the timer as well as on ticks.
   // This prevents the command waiting indefinitely for a new tick.
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

         GlobalVariableSet(
            "GoldCloseAll_"+(string)InpAccountId,
            0.0
         );

         Print("Close-all request completed: no matching positions remain.");
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

   // Preserve original signal observation.
   signalEngine.Observe(tick.bid,tick.ask);

   // Position management is performed by OnTimer.
   // New entries are handled here only.

   if(g_closeAllRequested)
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

   // ORIGINAL SIGNAL ENGINE: unchanged.
   int confidence=0;
   ENUM_ORDER_TYPE side;

   if(!signalEngine.GetSignal(side,confidence))
      return;

   // Respect broker-supported direction.
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

   // ORIGINAL EQUITY-BASED LOT CALCULATION.
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

   // ORIGINAL STOP/TARGET STRATEGY: unchanged.
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

   // An accepted order is not automatically a filled position.
   // PLACED is deliberately not treated as a confirmed execution.
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
         "Broker accepted the order but has not confirmed a fill yet. ",
         "Order=",
         orderTicket
      );
   }
   else if(ok)
   {
      Print(
         "Trade request returned without a confirmed matching entry deal. ",
         "Retcode=",
         retcode
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
// CONFIRM A BROKER ENTRY DEAL
//+------------------------------------------------------------------+

bool EntryDealExists(
   ulong orderTicket,
   ulong dealTicket,
   ENUM_ORDER_TYPE side
)
{
   datetime now=TimeCurrent();

   if(now<=0)
      return false;

   if(!HistorySelect(now-600,now+60))
      return false;

   if(dealTicket>0)
   {
      if(
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
// SAVE BROKER-CONFIRMED ORIGINAL ENTRY CONTEXT
// Aggregates partial fills belonging to the same position ID.
//+------------------------------------------------------------------+

bool SaveConfirmedEntryContext(
   ulong orderTicket,
   ulong dealTicket,
   ENUM_ORDER_TYPE side,
   int confidence
)
{
   datetime now=TimeCurrent();

   if(now<=0)
      return false;

   if(!HistorySelect(now-600,now+60))
   {
      Print("Cannot read recent deal history.");
      return false;
   }

   // Deal fills may create more than one position identifier.
   // Aggregate each identifier separately.
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
      Print(
         "No matching broker entry deals found for order ",
         orderTicket
      );

      return false;
   }

   bool anyContextSaved=false;

   for(int n=0;n<ArraySize(positionIds);n++)
   {
      ulong positionId=positionIds[n];

      double fillVolume=totalVolumes[n];

      if(fillVolume<=0.0)
         continue;

      double averageEntry=
         weightedPrices[n]/fillVolume;

      // Never overwrite the original context of a position
      // already being managed.
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

         long positionType=
            PositionGetInteger(POSITION_TYPE);

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
         Print(
            "Position not found after confirmed fill. ID=",
            positionId
         );

         continue;
      }

      // Do not create an incorrect original context when a netting
      // position already contained older volume.
      double volumeTolerance=
         MathMax(
            SymbolInfoDouble(g_symbol,SYMBOL_VOLUME_STEP)*0.5,
            0.00000001
         );

      if(
         MathAbs(currentPositionVolume-fillVolume)>
         volumeTolerance
      )
      {
         Print(
            "Context not saved: current net position volume differs ",
            "from this order's confirmed fills. Position ID=",
            positionId
         );

         continue;
      }

      if(initialSL<=0.0 || initialTP<=0.0)
      {
         Print(
            "Context not saved: broker-confirmed initial SL/TP ",
            "could not be verified. Position ID=",
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
            "Original entry context saved.",
            " Account=",InpAccountId,
            " Position ID=",positionId,
            " Entry=",DoubleToString(averageEntry,_Digits),
            " SL=",DoubleToString(initialSL,_Digits),
            " TP=",DoubleToString(initialTP,_Digits),
            " Volume=",DoubleToString(fillVolume,2)
         );
      }
      else
      {
         Print(
            "TradeRecovery refused to save context. Position ID=",
            positionId
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
   // An explicitly requested symbol must not silently fall back
   // to another instrument.
   if(requested!="AUTO")
   {
      if(!SymbolSelect(requested,true))
      {
         Print("Requested symbol is unavailable: ",requested);
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
         if(!g_riskLocked && LocalEntryAuthorization())
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
         StringFind(
            permission,
            "\"entries_allowed\":true"
         )>=0;

      g_enabled=
         backendAllowed &&
         LocalEntryAuthorization() &&
         !g_riskLocked &&
         !g_emergency;
   }
   else
   {
      // Fail closed for new entries.
      // Open positions continue to be managed.
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

      // HistoryDealGetTicket provides the deal ticket.
      // Do not call HistoryDealSelect inside this indexed loop.
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
