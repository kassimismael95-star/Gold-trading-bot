
#ifndef GOLD_POSITION_MANAGER
#define GOLD_POSITION_MANAGER

#include <Trade/Trade.mqh>
#include "SignalEngine.mqh"
#include "PositionTracker.mqh"
#include "TrailingStopManager.mqh"
#include "MarketAnalyzer.mqh"

// Post-entry management only.
// This class never opens, reverses, or changes new entries.
class CPositionManager
{
private:
   CPositionTracker tracker;
   CTrailingStopManager trailing;
   CMarketAnalyzer market;

   string StateKey(string name, ulong identifier)
   {
      return "GoldPM_" + name + "_" + (string)identifier;
   }

   int VolumePrecision(double step)
   {
      int digits = 0;

      while(digits < 8 &&
            MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001)
      {
         digits++;
      }

      return digits;
   }

   bool IsBuy(ENUM_POSITION_TYPE direction)
   {
      return direction == POSITION_TYPE_BUY;
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
         if(candidate >= tick.bid ||
            tick.bid - candidate < minimumDistance)
            return false;
      }
      else
      {
         if(candidate <= tick.ask ||
            candidate - tick.ask < minimumDistance)
            return false;
      }

      if(!PositionSelectByTicket(ticket))
         return false;

      bool requested =
         trade.PositionModify(ticket, candidate, currentTP);

      if(!requested)
      {
         Print(
            "Stop modification rejected. Ticket=", ticket,
            " Retcode=", trade.ResultRetcode(),
            " ", trade.ResultRetcodeDescription()
         );
         return false;
      }

      // Confirm the actual broker-side stop.
      if(!PositionSelectByTicket(ticket))
         return false;

      double confirmedSL = PositionGetDouble(POSITION_SL);

      if(IsBuy(direction))
         return confirmedSL >= candidate - point;

      return confirmedSL <= candidate + point;
   }

   double GetInitialRisk(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      ulong identifier = tracker.Identifier(ticket);

      if(identifier == 0)
         return 0.0;

      string key = StateKey("InitialRisk", identifier);

      if(GlobalVariableCheck(key))
      {
         double savedRisk = GlobalVariableGet(key);

         if(savedRisk > 0.0)
            return savedRisk;
      }

      double openPrice =
         tracker.OpenPrice(ticket, symbol, magic);

      double stopLoss =
         tracker.StopLoss(ticket, symbol, magic);

      // Do not invent an initial risk for an unprotected position.
      if(openPrice <= 0.0 || stopLoss <= 0.0)
      {
         Print(
            "Cannot establish initial risk. Ticket=", ticket,
            ". No valid broker-side stop loss was found."
         );
         return 0.0;
      }

      double risk = MathAbs(openPrice - stopLoss);

      if(risk <= 0.0)
         return 0.0;

      GlobalVariableSet(key, risk);

      return risk;
   }

   double PartialVolume(string symbol, double currentVolume)
   {
      double minimum =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

      double maximum =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);

      double step =
         SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      if(minimum <= 0.0 || step <= 0.0 || maximum < minimum)
         return 0.0;

      // Leave at least the broker's minimum volume open.
      if(currentVolume < minimum * 2.0)
         return 0.0;

      double requested = currentVolume * 0.50;

      double volume =
         MathFloor(requested / step + 0.00000001) * step;

      volume = NormalizeDouble(volume, VolumePrecision(step));

      if(volume < minimum || volume > maximum)
         return 0.0;

      if(currentVolume - volume < minimum - 0.00000001)
         return 0.0;

      return volume;
   }

   bool MarketSupportsPosition(
      SMarketState &state,
      ENUM_POSITION_TYPE direction
   )
   {
      return market.SupportsDirection(state, direction);
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
         return normalized >= 0.60 && state.trend >= 0;

      if(direction == POSITION_TYPE_SELL)
         return normalized <= -0.60 && state.trend <= 0;

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
      // Partial close is deliberately limited to hedging accounts.
      if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) !=
         ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
         return;

      if(!MarketSupportsPosition(state, direction))
         return;

      string key = StateKey("PartialDone", identifier);

      if(GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5)
         return;

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
            "Partial close rejected. Ticket=", ticket,
            " Retcode=", trade.ResultRetcode(),
            " ", trade.ResultRetcodeDescription()
         );
         return;
      }

      // Mark the action complete only after broker volume changes.
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
            "Partial close confirmed. Ticket=", ticket,
            " Previous volume=", currentVolume,
            " Remaining volume=", remaining
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

      string key = StateKey("TargetExtended", identifier);

      if(GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5)
         return;

      if(!PositionSelectByTicket(ticket))
         return;

      double currentTP = PositionGetDouble(POSITION_TP);
      double currentSL = PositionGetDouble(POSITION_SL);

      // Do not create a new TP if the original position had none.
      if(currentTP <= 0.0)
         return;

      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

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

      double minimumDistance = MinimumStopDistance(symbol);

      if(IsBuy(direction))
      {
         if(candidate <= currentTP + point ||
            candidate - tick.ask < minimumDistance)
            return;
      }
      else
      {
         if(candidate >= currentTP - point ||
            tick.bid - candidate < minimumDistance)
            return;
      }

      bool requested =
         trade.PositionModify(ticket, currentSL, candidate);

      if(!requested)
      {
         Print(
            "TP extension rejected. Ticket=", ticket,
            " Retcode=", trade.ResultRetcode(),
            " ", trade.ResultRetcodeDescription()
         );
         return;
      }

      if(!PositionSelectByTicket(ticket))
         return;

      double confirmedTP = PositionGetDouble(POSITION_TP);

      bool confirmed = IsBuy(direction)
         ? confirmedTP >= candidate - point
         : confirmedTP <= candidate + point;

      if(confirmed)
      {
         GlobalVariableSet(key, 1.0);

         Print(
            "TP extension confirmed. Ticket=", ticket,
            " New TP=", confirmedTP
         );
      }
   }

   void ManageOne(
      CTrade &trade,
      string symbol,
      long magic,
      ulong ticket,
      SMarketState &state
   )
   {
      if(!tracker.IsManagedPosition(ticket, symbol, magic))
         return;

      if(!PositionSelectByTicket(ticket))
         return;

      ENUM_POSITION_TYPE direction =
         (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

      double openPrice =
         PositionGetDouble(POSITION_PRICE_OPEN);

      double currentSL =
         PositionGetDouble(POSITION_SL);

      double currentTP =
         PositionGetDouble(POSITION_TP);

      if(openPrice <= 0.0 || currentSL <= 0.0)
         return;

      ulong identifier = tracker.Identifier(ticket);

      if(identifier == 0)
         return;

      double initialRisk =
         GetInitialRisk(ticket, symbol, magic);

      if(initialRisk <= 0.0)
         return;

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return;

      double currentPrice = IsBuy(direction)
         ? tick.bid
         : tick.ask;

      if(currentPrice <= 0.0)
         return;

      double favorableMovement = IsBuy(direction)
         ? currentPrice - openPrice
         : openPrice - currentPrice;

      double rMultiple = favorableMovement / initialRisk;

      // At +1R, attempt to protect a small portion of the gain.
      if(rMultiple >= 1.0)
      {
         double protectedPrice = IsBuy(direction)
            ? openPrice + initialRisk * 0.10
            : openPrice - initialRisk * 0.10;

         ImproveStop(
            trade,
            ticket,
            symbol,
            direction,
            protectedPrice,
            currentSL,
            currentTP
         );

         if(!PositionSelectByTicket(ticket))
            return;

         currentSL = PositionGetDouble(POSITION_SL);
         currentTP = PositionGetDouble(POSITION_TP);

         TryPartialProfit(
            trade,
            ticket,
            symbol,
            identifier,
            direction,
            state
         );

         TryExtendTarget(
            trade,
            ticket,
            symbol,
            identifier,
            direction,
            initialRisk,
            state
         );
      }

      // Do not trail before the position has moved +0.5R.
      if(rMultiple < 0.50 || !state.dataValid || state.atr <= 0.0)
         return;

      if(!PositionSelectByTicket(ticket))
         return;

      currentSL = PositionGetDouble(POSITION_SL);
      currentTP = PositionGetDouble(POSITION_TP);

      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(point <= 0.0)
         return;

      // Adapt trailing distance to volatility.
      double distance = trailing.AdaptiveDistance(
         symbol,
         state.atr,
         state.volatilityRatio
      );

      // Tighten somewhat when momentum is weakening.
      if(state.momentumWeakening)
         distance = MathMax(
            MinimumStopDistance(symbol),
            distance * 0.80
         );

      double candidate = trailing.ImprovedStop(
         direction,
         currentPrice,
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
         direction,
         candidate,
         currentSL,
         currentTP
      );
   }

public:

   // Existing EA interface retained.
   // This method only manages positions already confirmed by the broker.
   void Manage(
      CTrade &trade,
      string symbol,
      long magic,
      CSignalEngine &signalEngine
   )
   {
      if(symbol == "" || magic <= 0)
         return;

      SMarketState state;

      bool marketReady =
         market.Analyze(symbol, PERIOD_M1, state);

      if(!marketReady)
         return;

      // Snapshot tickets before managing them because positions
      // may change while broker operations are being processed.
      ulong tickets[];

      int total = PositionsTotal();

      ArrayResize(tickets, total);

      int used = 0;

      for(int i = total - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(tracker.IsManagedPosition(ticket, symbol, magic))
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
            tickets[j],
            state
         );
      }
   }
};

#endif
