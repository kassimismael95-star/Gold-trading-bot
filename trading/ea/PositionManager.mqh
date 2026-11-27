
#ifndef GOLD_POSITION_MANAGER
#define GOLD_POSITION_MANAGER

#include <Trade/Trade.mqh>

#include "SignalEngine.mqh"
#include "PositionTracker.mqh"
#include "TrailingStopManager.mqh"
#include "MarketAnalyzer.mqh"
#include "TradeRecovery.mqh"

class CPositionManager
{
private:

   CPositionTracker tracker;
   CTrailingStopManager trailing;
   CMarketAnalyzer market;
   CTradeRecovery recovery;

   // ---------------------------------------------------------
   // COMPACT, ACCOUNT-SCOPED PERSISTENT STATE
   // ---------------------------------------------------------

   string StateKey(
      string name,
      long accountId,
      ulong identifier
   )
   {
      // Keep keys short enough for MT5 Global Variables.
      return "GPM_" +
             (string)accountId + "_" +
             (string)identifier + "_" +
             name;
   }

   bool StateDone(
      string name,
      long accountId,
      ulong identifier
   )
   {
      string key = StateKey(
         name,
         accountId,
         identifier
      );

      return (
         GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5
      );
   }

   bool SaveState(
      string name,
      long accountId,
      ulong identifier
   )
   {
      string key = StateKey(
         name,
         accountId,
         identifier
      );

      if(GlobalVariableSet(key, 1.0) == 0)
         return false;

      GlobalVariableFlush();
      return true;
   }

   bool LoadNumber(
      string name,
      long accountId,
      ulong identifier,
      double &value
   )
   {
      string key = StateKey(
         name,
         accountId,
         identifier
      );

      if(!GlobalVariableCheck(key))
         return false;

      value = GlobalVariableGet(key);

      return MathIsValidNumber(value);
   }

   bool SaveNumber(
      string name,
      long accountId,
      ulong identifier,
      double value
   )
   {
      if(!MathIsValidNumber(value))
         return false;

      string key = StateKey(
         name,
         accountId,
         identifier
      );

      if(GlobalVariableSet(key, value) == 0)
         return false;

      GlobalVariableFlush();
      return true;
   }

   // ---------------------------------------------------------
   // BASIC POSITION HELPERS
   // ---------------------------------------------------------

   bool IsBuy(ENUM_POSITION_TYPE direction)
   {
      return direction == POSITION_TYPE_BUY;
   }

   bool ContextMatchesPosition(
      SOriginalEntryContext &context,
      ENUM_POSITION_TYPE direction
   )
   {
      if(!context.valid)
         return false;

      if(direction == POSITION_TYPE_BUY)
         return context.side == ORDER_TYPE_BUY;

      if(direction == POSITION_TYPE_SELL)
         return context.side == ORDER_TYPE_SELL;

      return false;
   }

   int VolumePrecision(double step)
   {
      int digits = 0;

      while(
         digits < 8 &&
         MathAbs(
            step - NormalizeDouble(step, digits)
         ) > 0.00000001
      )
      {
         digits++;
      }

      return digits;
   }

   double MinimumStopDistance(string symbol)
   {
      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      if(point <= 0.0)
         return 0.0;

      long stops =
         SymbolInfoInteger(
            symbol,
            SYMBOL_TRADE_STOPS_LEVEL
         );

      long freeze =
         SymbolInfoInteger(
            symbol,
            SYMBOL_TRADE_FREEZE_LEVEL
         );

      return (
         (double)MathMax(stops, freeze) + 2.0
      ) * point;
   }

   // ---------------------------------------------------------
   // PROTECTIVE STOP MANAGEMENT
   // ---------------------------------------------------------

   bool ImproveStop(
      CTrade &trade,
      ulong ticket,
      string symbol,
      ENUM_POSITION_TYPE direction,
      double candidate,
      double currentSL,
      double currentTP
   )
   {
      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(
            symbol,
            SYMBOL_DIGITS
         );

      if(candidate <= 0.0 || point <= 0.0)
         return false;

      candidate = NormalizeDouble(
         candidate,
         digits
      );

      // Never loosen an existing protective stop.
      if(IsBuy(direction))
      {
         if(
            currentSL > 0.0 &&
            candidate <= currentSL + point
         )
         {
            return false;
         }
      }
      else
      {
         if(
            currentSL > 0.0 &&
            candidate >= currentSL - point
         )
         {
            return false;
         }
      }

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      double minimumDistance =
         MinimumStopDistance(symbol);

      if(IsBuy(direction))
      {
         if(
            candidate >= tick.bid ||
            tick.bid - candidate < minimumDistance
         )
         {
            return false;
         }
      }
      else
      {
         if(
            candidate <= tick.ask ||
            candidate - tick.ask < minimumDistance
         )
         {
            return false;
         }
      }

      if(!PositionSelectByTicket(ticket))
         return false;

      bool requested =
         trade.PositionModify(
            ticket,
            candidate,
            currentTP
         );

      if(!requested)
      {
         Print(
            "Stop modification rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return false;
      }

      // Broker-side position state is authoritative.
      if(!PositionSelectByTicket(ticket))
         return false;

      double confirmedSL =
         PositionGetDouble(POSITION_SL);

      bool confirmed = false;

      if(IsBuy(direction))
      {
         confirmed =
            confirmedSL > 0.0 &&
            confirmedSL >= candidate - point;
      }
      else
      {
         confirmed =
            confirmedSL > 0.0 &&
            confirmedSL <= candidate + point;
      }

      if(!confirmed)
      {
         Print(
            "Broker stop confirmation failed. Ticket=",
            ticket,
            " Requested=",
            candidate,
            " Actual=",
            confirmedSL
         );
      }

      return confirmed;
   }

   // ---------------------------------------------------------
   // ORIGINAL RISK
   // ---------------------------------------------------------

   double InitialRisk(
      SOriginalEntryContext &context
   )
   {
      if(
         !context.valid ||
         context.entryPrice <= 0.0 ||
         context.initialStopLoss <= 0.0
      )
      {
         return 0.0;
      }

      return MathAbs(
         context.entryPrice -
         context.initialStopLoss
      );
   }

   double PartialVolume(
      string symbol,
      double currentVolume
   )
   {
      double minimum =
         SymbolInfoDouble(
            symbol,
            SYMBOL_VOLUME_MIN
         );

      double maximum =
         SymbolInfoDouble(
            symbol,
            SYMBOL_VOLUME_MAX
         );

      double step =
         SymbolInfoDouble(
            symbol,
            SYMBOL_VOLUME_STEP
         );

      if(
         minimum <= 0.0 ||
         step <= 0.0 ||
         maximum < minimum
      )
      {
         return 0.0;
      }

      if(currentVolume < minimum * 2.0)
         return 0.0;

      double requested =
         currentVolume * 0.50;

      double volume =
         MathFloor(
            requested / step + 0.00000001
         ) * step;

      volume = NormalizeDouble(
         volume,
         VolumePrecision(step)
      );

      if(
         volume < minimum ||
         volume > maximum
      )
      {
         return 0.0;
      }

      if(
         currentVolume - volume <
         minimum - 0.00000001
      )
      {
         return 0.0;
      }

      return volume;
   }

   // ---------------------------------------------------------
   // PERSISTENT PEAK-PROFIT TRACKER
   // ---------------------------------------------------------

   bool UpdatePeakPrice(
      long accountId,
      ulong identifier,
      ENUM_POSITION_TYPE direction,
      double currentPrice,
      double &peakPrice
   )
   {
      if(
         accountId <= 0 ||
         identifier == 0 ||
         currentPrice <= 0.0
      )
      {
         return false;
      }

      double savedPeak = 0.0;

      bool exists = LoadNumber(
         "PeakPrice",
         accountId,
         identifier,
         savedPeak
      );

      if(!exists || savedPeak <= 0.0)
      {
         peakPrice = currentPrice;

         return SaveNumber(
            "PeakPrice",
            accountId,
            identifier,
            peakPrice
         );
      }

      peakPrice = savedPeak;

      bool improved = false;

      if(direction == POSITION_TYPE_BUY)
      {
         if(currentPrice > peakPrice)
         {
            peakPrice = currentPrice;
            improved = true;
         }
      }
      else if(direction == POSITION_TYPE_SELL)
      {
         if(currentPrice < peakPrice)
         {
            peakPrice = currentPrice;
            improved = true;
         }
      }

      if(improved)
      {
         return SaveNumber(
            "PeakPrice",
            accountId,
            identifier,
            peakPrice
         );
      }

      return true;
   }

   // ---------------------------------------------------------
   // PROFIT TRACKING CALCULATIONS
   // ---------------------------------------------------------

   double FavorableDistance(
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double marketPrice
   )
   {
      if(direction == POSITION_TYPE_BUY)
         return marketPrice - entryPrice;

      if(direction == POSITION_TYPE_SELL)
         return entryPrice - marketPrice;

      return 0.0;
   }

   double PeakProfitR(
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double peakPrice,
      double initialRisk
   )
   {
      if(initialRisk <= 0.0)
         return 0.0;

      double favorable =
         FavorableDistance(
            direction,
            entryPrice,
            peakPrice
         );

      return MathMax(
         0.0,
         favorable / initialRisk
      );
   }

   double CurrentProfitR(
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double currentPrice,
      double initialRisk
   )
   {
      if(initialRisk <= 0.0)
         return 0.0;

      double favorable =
         FavorableDistance(
            direction,
            entryPrice,
            currentPrice
         );

      return favorable / initialRisk;
   }

   // ---------------------------------------------------------
   // PROFIT-RETRACEMENT PROTECTION
   // ---------------------------------------------------------

   void ProtectPeakProfit(
      CTrade &trade,
      ulong ticket,
      string symbol,
      long accountId,
      ulong identifier,
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double initialRisk,
      double currentPrice,
      double currentSL,
      double currentTP,
      SMarketState &state
   )
   {
      if(
         initialRisk <= 0.0 ||
         entryPrice <= 0.0 ||
         currentPrice <= 0.0
      )
      {
         return;
      }

      double peakPrice = 0.0;

      if(
         !UpdatePeakPrice(
            accountId,
            identifier,
            direction,
            currentPrice,
            peakPrice
         )
      )
      {
         Print(
            "Peak-profit state could not be saved. ",
            "Ticket=",
            ticket
         );

         return;
      }

      double peakR =
         PeakProfitR(
            direction,
            entryPrice,
            peakPrice,
            initialRisk
         );

      double currentR =
         CurrentProfitR(
            direction,
            entryPrice,
            currentPrice,
            initialRisk
         );

      double givebackR =
         peakR - currentR;

      // A trade must first develop meaningful profit.
      if(peakR < 0.75)
         return;

      // Protect when a meaningful portion of peak profit
      // has been surrendered or momentum is weakening.
      bool retracementDetected =
         givebackR >= 0.20;

      bool momentumWarning =
         state.dataValid &&
         state.momentumWeakening;

      if(
         !retracementDetected &&
         !momentumWarning
      )
      {
         return;
      }

      // Retain at least 60% of the favourable price move
      // measured from the original entry to the peak.
      // The minimum lock is 0.10R.
      double lockedDistance =
         MathMax(
            initialRisk * 0.10,
            (peakPrice - entryPrice) *
            (direction == POSITION_TYPE_BUY ? 0.60 : 0.0)
         );

      if(direction == POSITION_TYPE_SELL)
      {
         lockedDistance =
            MathMax(
               initialRisk * 0.10,
               (entryPrice - peakPrice) * 0.60
            );
      }

      double candidate = 0.0;

      if(direction == POSITION_TYPE_BUY)
      {
         candidate =
            entryPrice + lockedDistance;
      }
      else
      {
         candidate =
            entryPrice - lockedDistance;
      }

      candidate = NormalizeDouble(
         candidate,
         (int)SymbolInfoInteger(
            symbol,
            SYMBOL_DIGITS
         )
      );

      bool improved =
         ImproveStop(
            trade,
            ticket,
            symbol,
            direction,
            candidate,
            currentSL,
            currentTP
         );

      if(improved)
      {
         Print(
            "Peak-profit protection confirmed. ",
            "Ticket=",
            ticket,
            " Peak R=",
            DoubleToString(peakR, 2),
            " Current R=",
            DoubleToString(currentR, 2),
            " Giveback R=",
            DoubleToString(givebackR, 2),
            " New SL=",
            candidate
         );
      }
   }

   // ---------------------------------------------------------
   // MARKET CONDITION HELPERS
   // ---------------------------------------------------------

   bool StrongMomentumSupports(
      SMarketState &state,
      ENUM_POSITION_TYPE direction
   )
   {
      if(!state.dataValid || state.atr <= 0.0)
         return false;

      double normalized =
         market.NormalizedMomentum(state);

      if(direction == POSITION_TYPE_BUY)
      {
         return (
            normalized >= 0.60 &&
            state.trend >= 0
         );
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return (
            normalized <= -0.60 &&
            state.trend <= 0
         );
      }

      return false;
   }

   bool StrongOppositeThesis(
      SMarketState &state,
      ENUM_POSITION_TYPE direction
   )
   {
      if(!state.dataValid || state.atr <= 0.0)
         return false;

      if(!state.momentumStrengthening)
         return false;

      double normalized =
         market.NormalizedMomentum(state);

      if(direction == POSITION_TYPE_BUY)
      {
         return (
            normalized <= -0.80 &&
            state.trend < 0
         );
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return (
            normalized >= 0.80 &&
            state.trend > 0
         );
      }

      return false;
   }

   // ---------------------------------------------------------
   // PARTIAL PROFIT
   // ---------------------------------------------------------

   void TryPartialProfit(
      CTrade &trade,
      ulong ticket,
      string symbol,
      long accountId,
      ulong identifier,
      ENUM_POSITION_TYPE direction,
      SMarketState &state
   )
   {
      if(
         AccountInfoInteger(ACCOUNT_MARGIN_MODE) !=
         ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
      )
      {
         return;
      }

      if(!state.dataValid)
         return;

      if(!market.SupportsDirection(state, direction))
         return;

      if(
         StateDone(
            "PartialDone",
            accountId,
            identifier
         )
      )
      {
         return;
      }

      if(!PositionSelectByTicket(ticket))
         return;

      double currentVolume =
         PositionGetDouble(POSITION_VOLUME);

      double closeVolume =
         PartialVolume(symbol, currentVolume);

      if(closeVolume <= 0.0)
         return;

      bool requested =
         trade.PositionClosePartial(
            ticket,
            closeVolume
         );

      if(!requested)
      {
         Print(
            "Partial close rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return;
      }

      if(!PositionSelectByTicket(ticket))
      {
         SaveState(
            "PartialDone",
            accountId,
            identifier
         );

         Print(
            "Position disappeared after partial close. Ticket=",
            ticket
         );

         return;
      }

      double remaining =
         PositionGetDouble(POSITION_VOLUME);

      if(
         remaining <
         currentVolume - 0.00000001
      )
      {
         SaveState(
            "PartialDone",
            accountId,
            identifier
         );

         Print(
            "Partial close confirmed. Ticket=",
            ticket,
            " Previous volume=",
            currentVolume,
            " Remaining volume=",
            remaining
         );
      }
      else
      {
         Print(
            "Partial close was not confirmed by broker. Ticket=",
            ticket
         );
      }
   }

   // ---------------------------------------------------------
   // TAKE-PROFIT EXTENSION
   // ---------------------------------------------------------

   void TryExtendTarget(
      CTrade &trade,
      ulong ticket,
      string symbol,
      long accountId,
      ulong identifier,
      ENUM_POSITION_TYPE direction,
      double initialRisk,
      SMarketState &state
   )
   {
      if(initialRisk <= 0.0)
         return;

      if(!StrongMomentumSupports(state, direction))
         return;

      if(
         StateDone(
            "TargetExtended",
            accountId,
            identifier
         )
      )
      {
         return;
      }

      if(!PositionSelectByTicket(ticket))
         return;

      double currentTP =
         PositionGetDouble(POSITION_TP);

      double currentSL =
         PositionGetDouble(POSITION_SL);

      if(currentTP <= 0.0)
         return;

      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(
            symbol,
            SYMBOL_DIGITS
         );

      if(point <= 0.0)
         return;

      double extension =
         initialRisk * 0.50;

      double candidate = IsBuy(direction)
         ? currentTP + extension
         : currentTP - extension;

      candidate = NormalizeDouble(
         candidate,
         digits
      );

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return;

      double minimumDistance =
         MinimumStopDistance(symbol);

      if(IsBuy(direction))
      {
         if(
            candidate <= currentTP + point ||
            candidate - tick.ask < minimumDistance
         )
         {
            return;
         }
      }
      else
      {
         if(
            candidate >= currentTP - point ||
            tick.bid - candidate < minimumDistance
         )
         {
            return;
         }
      }

      bool requested =
         trade.PositionModify(
            ticket,
            currentSL,
            candidate
         );

      if(!requested)
      {
         Print(
            "TP extension rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return;
      }

      if(!PositionSelectByTicket(ticket))
         return;

      double confirmedTP =
         PositionGetDouble(POSITION_TP);

      bool confirmed = IsBuy(direction)
         ? confirmedTP >= candidate - point
         : confirmedTP <= candidate + point;

      if(confirmed)
      {
         SaveState(
            "TargetExtended",
            accountId,
            identifier
         );

         Print(
            "TP extension confirmed. Ticket=",
            ticket,
            " New TP=",
            confirmedTP
         );
      }
      else
      {
         Print(
            "TP extension not confirmed. Ticket=",
            ticket,
            " Requested=",
            candidate,
            " Actual=",
            confirmedTP
         );
      }
   }

   // ---------------------------------------------------------
   // INVALIDATED TRADE THESIS
   // ---------------------------------------------------------

   bool CloseInvalidatedPosition(
      CTrade &trade,
      ulong ticket,
      long accountId,
      ulong identifier,
      SManagedPositionSnapshot &snapshot,
      SMarketState &state
   )
   {
      if(
         !StrongOppositeThesis(
            state,
            snapshot.direction
         )
      )
      {
         return false;
      }

      if(snapshot.floatingProfit >= 0.0)
         return false;

      if(
         StateDone(
            "ThesisExit",
            accountId,
            identifier
         )
      )
      {
         return false;
      }

      if(!PositionSelectByTicket(ticket))
         return false;

      bool requested =
         trade.PositionClose(ticket);

      if(!requested)
      {
         Print(
            "Thesis exit rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return false;
      }

      if(!PositionSelectByTicket(ticket))
      {
         SaveState(
            "ThesisExit",
            accountId,
            identifier
         );

         Print(
            "Thesis invalidation close confirmed. Ticket=",
            ticket
         );

         return true;
      }

      Print(
         "Thesis exit not confirmed. Ticket=",
         ticket,
         " Remaining volume=",
         PositionGetDouble(POSITION_VOLUME)
      );

      return false;
   }

   // ---------------------------------------------------------
   // MANAGE ONE BROKER-CONFIRMED POSITION
   // ---------------------------------------------------------

   void ManageOne(
      CTrade &trade,
      string symbol,
      long magic,
      long accountId,
      ulong ticket,
      SMarketState &state
   )
   {
      SManagedPositionSnapshot snapshot;

      if(
         !tracker.ReadSnapshot(
            ticket,
            symbol,
            magic,
            snapshot
         )
      )
      {
         return;
      }

      if(!snapshot.valid)
         return;

      SOriginalEntryContext context;

      bool hasContext =
         recovery.LoadEntryContext(
            accountId,
            snapshot.identifier,
            context
         );

      if(
         hasContext &&
         !ContextMatchesPosition(
            context,
            snapshot.direction
         )
      )
      {
         hasContext = false;
         context.valid = false;

         Print(
            "Entry context direction mismatch. ",
            "R-based management disabled. Identifier=",
            snapshot.identifier
         );
      }

      if(!hasContext)
      {
         Print(
            "Original entry context unavailable. ",
            "Broker SL/TP remain active. ",
            "Identifier=",
            snapshot.identifier
         );

         return;
      }

      double initialRisk =
         InitialRisk(context);

      if(initialRisk <= 0.0)
      {
         Print(
            "Invalid original risk. R-based management ",
            "disabled. Ticket=",
            ticket
         );

         return;
      }

      double entryPrice =
         context.entryPrice;

      double favorableMovement =
         FavorableDistance(
            snapshot.direction,
            entryPrice,
            snapshot.currentPrice
         );

      double rMultiple =
         favorableMovement / initialRisk;

      // Update the persistent peak even before a profit
      // protection trigger is reached.
      double peakPrice = 0.0;

      UpdatePeakPrice(
         accountId,
         snapshot.identifier,
         snapshot.direction,
         snapshot.currentPrice,
         peakPrice
      );

      // Evaluate thesis invalidation only with valid analysis.
      if(state.dataValid)
      {
         if(
            CloseInvalidatedPosition(
               trade,
               ticket,
               accountId,
               snapshot.identifier,
               snapshot,
               state
            )
         )
         {
            return;
         }
      }

      // ------------------------------------------------------
      // +1R PROFIT PROTECTION
      // ------------------------------------------------------

      if(rMultiple >= 1.0)
      {
         double protectedPrice =
            IsBuy(snapshot.direction)
            ? entryPrice + initialRisk * 0.10
            : entryPrice - initialRisk * 0.10;

         ImproveStop(
            trade,
            ticket,
            symbol,
            snapshot.direction,
            protectedPrice,
            snapshot.stopLoss,
            snapshot.takeProfit
         );

         if(!PositionSelectByTicket(ticket))
            return;

         if(state.dataValid)
         {
            TryPartialProfit(
               trade,
               ticket,
               symbol,
               accountId,
               snapshot.identifier,
               snapshot.direction,
               state
            );

            TryExtendTarget(
               trade,
               ticket,
               symbol,
               accountId,
               snapshot.identifier,
               snapshot.direction,
               initialRisk,
               state
            );
         }
      }

      // ------------------------------------------------------
      // PROFIT PEAK / RETRACEMENT PROTECTION
      // ------------------------------------------------------

      if(rMultiple >= 0.50)
      {
         if(!PositionSelectByTicket(ticket))
            return;

         double latestSL =
            PositionGetDouble(POSITION_SL);

         double latestTP =
            PositionGetDouble(POSITION_TP);

         ProtectPeakProfit(
            trade,
            ticket,
            symbol,
            accountId,
            snapshot.identifier,
            snapshot.direction,
            entryPrice,
            initialRisk,
            snapshot.currentPrice,
            latestSL,
            latestTP,
            state
         );
      }

      // ------------------------------------------------------
      // VOLATILITY-AWARE TRAILING AFTER +0.5R
      // ------------------------------------------------------

      if(
         rMultiple < 0.50 ||
         !state.dataValid ||
         state.atr <= 0.0
      )
      {
         return;
      }

      if(!PositionSelectByTicket(ticket))
         return;

      double currentSL =
         PositionGetDouble(POSITION_SL);

      double currentTP =
         PositionGetDouble(POSITION_TP);

      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(
            symbol,
            SYMBOL_DIGITS
         );

      if(point <= 0.0)
         return;

      double distance =
         trailing.AdaptiveDistance(
            symbol,
            state.atr,
            state.volatilityRatio
         );

      if(distance <= 0.0)
         return;

      if(state.momentumWeakening)
      {
         distance = MathMax(
            MinimumStopDistance(symbol),
            distance * 0.80
         );
      }

      double candidate =
         trailing.ImprovedStop(
            snapshot.direction,
            snapshot.currentPrice,
            currentSL,
            distance,
            point,
            digits
         );

      if(candidate <= 0.0)
         return;

      ImproveStop(
         trade,
         ticket,
         symbol,
         snapshot.direction,
         candidate,
         currentSL,
         currentTP
      );
   }

   // ---------------------------------------------------------
   // MANAGE ALL POSITIONS FOR THIS ACCOUNT AND EA
   // ---------------------------------------------------------

   void ManageAll(
      CTrade &trade,
      string symbol,
      long magic,
      long accountId
   )
   {
      if(
         symbol == "" ||
         magic <= 0 ||
         accountId <= 0
      )
      {
         return;
      }

      SMarketState state;

      state.atr = 0.0;
      state.averageRange = 0.0;
      state.volatilityRatio = 0.0;
      state.momentum = 0.0;
      state.previousMomentum = 0.0;
      state.trend = 0;
      state.momentumStrengthening = false;
      state.momentumWeakening = false;
      state.dataValid = false;

      bool analysisAvailable =
         market.Analyze(
            symbol,
            PERIOD_M1,
            state
         );

      if(!analysisAvailable)
      {
         state.dataValid = false;

         Print(
            "Market analysis unavailable for ",
            symbol,
            ". Continuing basic position protection."
         );
      }

      ulong tickets[];

      int total = PositionsTotal();

      ArrayResize(tickets, total);

      int used = 0;

      for(int i = total - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(
            tracker.IsManagedPosition(
               ticket,
               symbol,
               magic
            )
         )
         {
            tickets[used] = ticket;
            used++;
         }
      }

      ArrayResize(tickets, used);

      for(int j = 0; j < used; j++)
      {
         ManageOne(
            trade,
            symbol,
            magic,
            accountId,
            tickets[j],
            state
         );
      }
   }

public:

   void Manage(
      CTrade &trade,
      string symbol,
      long magic,
      long accountId,
      CSignalEngine &signalEngine
   )
   {
      ManageAll(
         trade,
         symbol,
         magic,
         accountId
      );
   }

   // Compatibility interface for existing callers.
   void Manage(
      CTrade &trade,
      string symbol,
      long magic,
      CSignalEngine &signalEngine
   )
   {
      long login =
         AccountInfoInteger(ACCOUNT_LOGIN);

      ManageAll(
         trade,
         symbol,
         magic,
         login
      );
   }
};

#endif
