
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

   string StateKey(
      string name,
      ulong identifier
   )
   {
      return "GoldPM_" + name + "_" + (string)identifier;
   }

   bool IsBuy(ENUM_POSITION_TYPE direction)
   {
      return direction == POSITION_TYPE_BUY;
   }

   int VolumePrecision(double step)
   {
      int digits = 0;

      while(
         digits < 8 &&
         MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001
      )
      {
         digits++;
      }

      return digits;
   }

   double MinimumStopDistance(string symbol)
   {
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

      if(point <= 0.0)
         return 0.0;

      long stops =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

      long freeze =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);

      return ((double)MathMax(stops, freeze) + 2.0) * point;
   }

   bool BrokerPositionExists(ulong ticket)
   {
      return ticket > 0 && PositionSelectByTicket(ticket);
   }

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
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(candidate <= 0.0 || point <= 0.0)
         return false;

      candidate = NormalizeDouble(candidate, digits);

      // Never loosen an existing protective stop.
      if(IsBuy(direction))
      {
         if(currentSL > 0.0 && candidate <= currentSL + point)
            return false;
      }
      else
      {
         if(currentSL > 0.0 && candidate >= currentSL - point)
            return false;
      }

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      double minimumDistance = MinimumStopDistance(symbol);

      if(IsBuy(direction))
      {
         if(
            candidate >= tick.bid ||
            tick.bid - candidate < minimumDistance
         )
            return false;
      }
      else
      {
         if(
            candidate <= tick.ask ||
            candidate - tick.ask < minimumDistance
         )
            return false;
      }

      if(!PositionSelectByTicket(ticket))
         return false;

      bool requested =
         trade.PositionModify(ticket, candidate, currentTP);

      if(!requested)
      {
         Print(
            "Position stop modification rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return false;
      }

      if(!PositionSelectByTicket(ticket))
         return false;

      double confirmedSL =
         PositionGetDouble(POSITION_SL);

      bool confirmed = IsBuy(direction)
         ? confirmedSL >= candidate - point
         : confirmedSL <= candidate + point;

      if(!confirmed)
      {
         Print(
            "Broker did not confirm requested stop. Ticket=",
            ticket
         );
      }

      return confirmed;
   }

   double InitialRisk(
      SManagedPositionSnapshot &snapshot,
      SOriginalEntryContext &context
   )
   {
      // The saved original SL is authoritative for initial risk.
      if(
         context.valid &&
         context.entryPrice > 0.0 &&
         context.initialStopLoss > 0.0
      )
      {
         double savedRisk =
            MathAbs(
               context.entryPrice -
               context.initialStopLoss
            );

         if(savedRisk > 0.0)
            return savedRisk;
      }

      // Fallback for older positions with no saved context.
      // Never invent risk if the position has no valid SL.
      if(
         snapshot.openPrice > 0.0 &&
         snapshot.stopLoss > 0.0
      )
      {
         double brokerRisk =
            MathAbs(
               snapshot.openPrice -
               snapshot.stopLoss
            );

         if(brokerRisk > 0.0)
            return brokerRisk;
      }

      return 0.0;
   }

   double PartialVolume(
      string symbol,
      double currentVolume
   )
   {
      double minimum =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

      double maximum =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);

      double step =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

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

      double requested = currentVolume * 0.50;

      double volume =
         MathFloor(
            requested / step + 0.00000001
         ) * step;

      volume = NormalizeDouble(
         volume,
         VolumePrecision(step)
      );

      if(volume < minimum || volume > maximum)
         return 0.0;

      if(currentVolume - volume < minimum - 0.00000001)
         return 0.0;

      return volume;
   }

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
         return
            normalized >= 0.60 &&
            state.trend >= 0;
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return
            normalized <= -0.60 &&
            state.trend <= 0;
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

      // Require both strong opposite momentum and an opposite trend.
      if(direction == POSITION_TYPE_BUY)
      {
         return
            normalized <= -0.80 &&
            state.trend < 0;
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return
            normalized >= 0.80 &&
            state.trend > 0;
      }

      return false;
   }

   void TryPartialProfit(
      CTrade &trade,
      ulong ticket,
      string symbol,
      ulong identifier,
      ENUM_POSITION_TYPE direction,
      SMarketState &state
   )
   {
      // Partial close is supported here only for hedging accounts.
      if(
         AccountInfoInteger(ACCOUNT_MARGIN_MODE) !=
         ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
      )
      {
         return;
      }

      if(!market.SupportsDirection(state, direction))
         return;

      string key =
         StateKey("PartialDone", identifier);

      if(
         GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5
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
         trade.PositionClosePartial(ticket, closeVolume);

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

      // Confirm the broker actually reduced the position.
      if(!PositionSelectByTicket(ticket))
      {
         GlobalVariableSet(key, 1.0);
         return;
      }

      double remaining =
         PositionGetDouble(POSITION_VOLUME);

      if(remaining < currentVolume - 0.00000001)
      {
         GlobalVariableSet(key, 1.0);

         Print(
            "Partial close confirmed. Ticket=",
            ticket,
            " Previous volume=",
            currentVolume,
            " Remaining volume=",
            remaining
         );
      }
   }

   void TryExtendTarget(
      CTrade &trade,
      ulong ticket,
      string symbol,
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

      string key =
         StateKey("TargetExtended", identifier);

      if(
         GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5
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

      // Never invent a target for a position without an original TP.
      if(currentTP <= 0.0)
         return;

      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(point <= 0.0)
         return;

      double extension = initialRisk * 0.50;

      double candidate = IsBuy(direction)
         ? currentTP + extension
         : currentTP - extension;

      candidate = NormalizeDouble(candidate, digits);

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
         GlobalVariableSet(key, 1.0);

         Print(
            "TP extension confirmed. Ticket=",
            ticket,
            " New TP=",
            confirmedTP
         );
      }
   }

   bool CloseInvalidatedPosition(
      CTrade &trade,
      ulong ticket,
      ulong identifier,
      SManagedPositionSnapshot &snapshot,
      SMarketState &state
   )
   {
      if(!StrongOppositeThesis(state, snapshot.direction))
         return false;

      // Do not close a profitable trade solely because momentum
      // briefly weakens. Require the position to be losing.
      if(snapshot.floatingProfit >= 0.0)
         return false;

      string key =
         StateKey("ThesisExit", identifier);

      if(
         GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5
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

      // Verify that the broker actually removed this position.
      if(!PositionSelectByTicket(ticket))
      {
         GlobalVariableSet(key, 1.0);

         Print(
            "Thesis invalidation close confirmed. Ticket=",
            ticket
         );

         return true;
      }

      Print(
         "Thesis exit requested but position remains open. Ticket=",
         ticket,
         " Remaining volume=",
         PositionGetDouble(POSITION_VOLUME)
      );

      return false;
   }

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

      if(!hasContext)
      {
         context.valid = false;

         Print(
            "Original entry context unavailable. ",
            "Position remains under broker-SL protection. ",
            "Identifier=",
            snapshot.identifier
         );
      }

      double initialRisk =
         InitialRisk(snapshot, context);

      if(initialRisk <= 0.0)
      {
         Print(
            "Position cannot be managed using R-based rules ",
            "because its original risk is unavailable. Ticket=",
            ticket
         );

         return;
      }

      double favorableMovement =
         IsBuy(snapshot.direction)
         ? snapshot.currentPrice - snapshot.openPrice
         : snapshot.openPrice - snapshot.currentPrice;

      double rMultiple =
         favorableMovement / initialRisk;

      // Original thesis invalidation is evaluated only when
      // the saved entry context exists.
      if(hasContext && state.dataValid)
      {
         if(
            CloseInvalidatedPosition(
               trade,
               ticket,
               snapshot.identifier,
               snapshot,
               state
            )
         )
         {
            return;
         }
      }

      // At +1R, attempt to protect a small portion of profit.
      if(rMultiple >= 1.0)
      {
         double protectedPrice = IsBuy(snapshot.direction)
            ? snapshot.openPrice + initialRisk * 0.10
            : snapshot.openPrice - initialRisk * 0.10;

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

         TryPartialProfit(
            trade,
            ticket,
            symbol,
            snapshot.identifier,
            snapshot.direction,
            state
         );

         TryExtendTarget(
            trade,
            ticket,
            symbol,
            snapshot.identifier,
            snapshot.direction,
            initialRisk,
            state
         );
      }

      // Volatility-aware trailing begins after +0.5R.
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
         (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

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

      // Tighten cautiously when momentum weakens.
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

   void ManageAll(
      CTrade &trade,
      string symbol,
      long magic,
      long accountId
   )
   {
      if(symbol == "" || magic <= 0 || accountId <= 0)
         return;

      SMarketState state;

      // If market analysis is unavailable, do not invent signals.
      // Broker-side SL and TP remain active.
      if(!market.Analyze(symbol, PERIOD_M1, state))
         return;

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

   // Preferred interface: uses the platform account ID
   // to recover the exact original entry context.
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

   // Compatibility interface for older EA callers.
   // It cannot load platform-specific entry context.
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
