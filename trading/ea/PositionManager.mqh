
#ifndef GOLD_POSITION_MANAGER
#define GOLD_POSITION_MANAGER

#include <Trade/Trade.mqh>
#include "SignalEngine.mqh"
#include "PositionTracker.mqh"
#include "TrailingStopManager.mqh"
#include "MarketAnalyzer.mqh"

// Manages each broker-confirmed position independently.
// Does not control entries or close positions as a basket.
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

   bool IsBuy(ENUM_POSITION_TYPE direction)
   {
      return direction == POSITION_TYPE_BUY;
   }

   bool MomentumAligned(
      ENUM_POSITION_TYPE direction,
      int score
   )
   {
      if(direction == POSITION_TYPE_BUY)
         return score >= 0;

      if(direction == POSITION_TYPE_SELL)
         return score <= 0;

      return false;
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

      if(candidate <= 0.0 || point <= 0.0)
         return false;

      // A BUY stop may only move upward.
      if(IsBuy(direction))
      {
         if(currentSL > 0.0 &&
            candidate <= currentSL + point)
            return false;
      }
      // A SELL stop may only move downward.
      else
      {
         if(currentSL > 0.0 &&
            candidate >= currentSL - point)
            return false;
      }

      double minimumDistance = MinimumStopDistance(symbol);

      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      if(IsBuy(direction))
      {
         if(tick.bid - candidate < minimumDistance)
            return false;
      }
      else
      {
         if(candidate - tick.ask < minimumDistance)
            return false;
      }

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

      // Verify the broker's actual position state.
      if(!PositionSelectByTicket(ticket))
         return false;

      double confirmedSL =
         PositionGetDouble(POSITION_SL);

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

      // Terminal global variables survive normal EA restarts.
      if(GlobalVariableCheck(key))
         return GlobalVariableGet(key);

      double openPrice =
         tracker.OpenPrice(ticket, symbol, magic);

      double stopLoss =
         tracker.StopLoss(ticket, symbol, magic);

      // Never invent a risk distance for a position without
      // an initial broker-side stop.
      if(openPrice <= 0.0 || stopLoss <= 0.0)
      {
         Print(
            "Position manager cannot establish initial risk. Ticket=",
            ticket,
            ". Existing position has no stop loss."
         );

         return 0.0;
      }

      double risk = MathAbs(openPrice - stopLoss);

      if(risk <= 0.0)
         return 0.0;

      GlobalVariableSet(key, risk);

      return risk;
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

      if(minimum <= 0.0 ||
         step <= 0.0 ||
         maximum < minimum)
         return 0.0;

      if(currentVolume < minimum * 2.0)
         return 0.0;

      double requested = currentVolume * 0.50;

      double volume =
         MathFloor(requested / step + 0.00000001) * step;

      volume = NormalizeDouble(
         volume,
         VolumePrecision(step)
      );

      if(volume < minimum)
         return 0.0;

      if(volume > maximum)
         return 0.0;

      if(currentVolume - volume < minimum - 0.00000001)
         return 0.0;

      return volume;
   }

   void TryPartialProfit(
      CTrade &trade,
      ulong ticket,
      string symbol,
      ulong identifier,
      int momentumScore,
      ENUM_POSITION_TYPE direction
   )
   {
      // Partial close is supported here only for hedging accounts.
      if(AccountInfoInteger(ACCOUNT_MARGIN_MODE) !=
         ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
         return;

      if(!MomentumAligned(direction, momentumScore))
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
            "Partial close rejected. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );

         return;
      }

      // Do not mark success until the broker confirms
      // that the remaining position volume has decreased.
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
            "Partial profit confirmed. Ticket=",
            ticket,
            " Closed volume=",
            closeVolume,
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
      int momentumScore
   )
   {
      if(initialRisk <= 0.0)
         return;

      // TP extension requires strong momentum in the
      // same direction as the individual position.
      bool strongMomentum = false;

      if(direction == POSITION_TYPE_BUY)
         strongMomentum = momentumScore >= 6;

      if(direction == POSITION_TYPE_SELL)
         strongMomentum = momentumScore <= -6;

      if(!strongMomentum)
         return;

      string key = StateKey("TargetExtended", identifier);

      if(GlobalVariableCheck(key) &&
         GlobalVariableGet(key) > 0.5)
         return;

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
         if(candidate <= currentTP + point)
            return;

         if(candidate - tick.ask < minimumDistance)
            return;
      }
      else
      {
         if(candidate >= currentTP - point)
            return;

         if(tick.bid - candidate < minimumDistance)
            return;
      }

      bool requested =
         trade.PositionModify(ticket, currentSL, candidate);

      if(!requested)
      {
         Print(
            "Target extension rejected. Ticket=",
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

   void ManageOne(
      CTrade &trade,
      string symbol,
      long magic,
      ulong ticket,
      int momentumScore,
      double atr
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

      double rMultiple =
         favorableMovement / initialRisk;

      // At +1R, protect a portion of the unrealized profit.
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

         // Re-read broker values after a successful modification.
         if(PositionSelectByTicket(ticket))
         {
            currentSL = PositionGetDouble(POSITION_SL);
            currentTP = PositionGetDouble(POSITION_TP);
         }

         // Partial profit is attempted once at +1R.
         TryPartialProfit(
            trade,
            ticket,
            symbol,
            identifier,
            momentumScore,
            direction
         );

         // Extend the target once if strong momentum supports it.
         TryExtendTarget(
            trade,
            ticket,
            symbol,
            identifier,
            direction,
            initialRisk,
            momentumScore
         );
      }

      // Begin volatility-aware trailing after +0.5R.
      if(rMultiple < 0.50 || atr <= 0.0)
         return;

      if(!PositionSelectByTicket(ticket))
         return;

      currentSL = PositionGetDouble(POSITION_SL);
      currentTP = PositionGetDouble(POSITION_TP);

      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      double distance =
         trailing.Distance(symbol, atr);

      double candidate =
         trailing.ImprovedStop(
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

   // This is the exact public interface expected by GoldScalperEA.mq5.
   void Manage(
      CTrade &trade,
      string symbol,
      long magic,
      CSignalEngine &signalEngine
   )
   {
      if(symbol == "" || magic <= 0)
         return;

      int momentumScore = 0;

      // Do not interpret the engine's default BUY signal as
      // live momentum until at least three observations exist.
      if(signalEngine.GetTickCount() >= 3)
         momentumScore = signalEngine.GetSignedMomentumScore();

      double atr =
         market.ATR(symbol, PERIOD_M1, 14);

      // Take a ticket snapshot before managing positions.
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

      // Every position is managed separately.
      for(int j = 0; j < used; j++)
      {
         ManageOne(
            trade,
            symbol,
            magic,
            tickets[j],
            momentumScore,
            atr
         );
      }
   }
};

#endif
