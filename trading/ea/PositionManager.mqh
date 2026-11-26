
#ifndef GOLD_POSITION_MANAGER
#define GOLD_POSITION_MANAGER

#include <Trade/Trade.mqh>
#include "TrailingStopManager.mqh"

class CPositionManager
{
private:
   CTrailingStopManager trailing;

   string StateKey(long identifier, string suffix)
   {
      return "GoldPosition_" +
             (string)AccountInfoInteger(ACCOUNT_LOGIN) +
             "_" + (string)identifier +
             "_" + suffix;
   }

   double LoadState(long identifier, string suffix, double fallback)
   {
      string key = StateKey(identifier, suffix);

      if(GlobalVariableCheck(key))
         return GlobalVariableGet(key);

      return fallback;
   }

   void SaveState(long identifier, string suffix, double value)
   {
      GlobalVariableSet(StateKey(identifier, suffix), value);
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

   bool IsModificationSuccessful(CTrade &trade)
   {
      uint code = trade.ResultRetcode();

      return code == TRADE_RETCODE_DONE ||
             code == TRADE_RETCODE_NO_CHANGES;
   }

   void ManageBuy(
      CTrade &trade,
      ulong ticket,
      long identifier,
      string symbol,
      MqlTick &tick,
      double open,
      double oldSL,
      double oldTP,
      double trailDistance,
      double minimumDistance,
      double point,
      int digits
   )
   {
      double bestPrice = LoadState(
         identifier,
         "best",
         open
      );

      if(tick.bid > bestPrice)
      {
         bestPrice = tick.bid;
         SaveState(identifier, "best", bestPrice);
      }

      // Do not trail until price has moved favourably.
      if(bestPrice <= open + 2.0 * point)
         return;

      double candidate = MathMax(
         open + 2.0 * point,
         bestPrice - trailDistance
      );

      candidate = NormalizeDouble(candidate, digits);

      // Stop must remain safely below the current bid.
      if(candidate >= tick.bid - minimumDistance)
         return;

      // Never move a stop backwards.
      if(oldSL > 0.0 && candidate <= oldSL + point)
         return;

      bool modified =
         trade.PositionModify(ticket, candidate, oldTP);

      if(!modified || !IsModificationSuccessful(trade))
      {
         Print(
            "BUY position stop modification failed. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );
      }
   }

   void ManageSell(
      CTrade &trade,
      ulong ticket,
      long identifier,
      string symbol,
      MqlTick &tick,
      double open,
      double oldSL,
      double oldTP,
      double trailDistance,
      double minimumDistance,
      double point,
      int digits
   )
   {
      double bestPrice = LoadState(
         identifier,
         "best",
         open
      );

      if(bestPrice == open || tick.ask < bestPrice)
      {
         bestPrice = tick.ask;
         SaveState(identifier, "best", bestPrice);
      }

      // Do not trail until price has moved favourably.
      if(bestPrice >= open - 2.0 * point)
         return;

      double candidate = MathMin(
         open - 2.0 * point,
         bestPrice + trailDistance
      );

      candidate = NormalizeDouble(candidate, digits);

      // Stop must remain safely above the current ask.
      if(candidate <= tick.ask + minimumDistance)
         return;

      // Never move a stop backwards.
      if(oldSL > 0.0 && candidate >= oldSL - point)
         return;

      bool modified =
         trade.PositionModify(ticket, candidate, oldTP);

      if(!modified || !IsModificationSuccessful(trade))
      {
         Print(
            "SELL position stop modification failed. Ticket=",
            ticket,
            " Retcode=",
            trade.ResultRetcode(),
            " ",
            trade.ResultRetcodeDescription()
         );
      }
   }

public:

   void Manage(
      CTrade &trade,
      string sym,
      long magic,
      CSignalEngine &signals
   )
   {
      MqlTick tick;

      if(!SymbolInfoTick(sym, tick))
         return;

      double point =
         SymbolInfoDouble(sym, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);

      if(point <= 0.0)
         return;

      // Calculate recent M1 average range.
      MqlRates rates[];
      ArraySetAsSeries(rates, true);

      int copied =
         CopyRates(sym, PERIOD_M1, 0, 15, rates);

      double atr = 0.0;

      if(copied > 1)
      {
         for(int r = 1; r < copied; r++)
         {
            atr += MathMax(
               0.0,
               rates[r].high - rates[r].low
            );
         }

         atr /= (double)(copied - 1);
      }

      double minimumDistance =
         MinimumStopDistance(sym);

      double trailDistance =
         trailing.Distance(sym, atr);

      if(trailDistance <= 0.0)
         return;

      // Every position is managed independently.
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(PositionGetString(POSITION_SYMBOL) != sym)
            continue;

         if(PositionGetInteger(POSITION_MAGIC) != magic)
            continue;

         long identifier =
            PositionGetInteger(POSITION_IDENTIFIER);

         if(identifier <= 0)
            continue;

         long type =
            PositionGetInteger(POSITION_TYPE);

         double open =
            PositionGetDouble(POSITION_PRICE_OPEN);

         double oldSL =
            PositionGetDouble(POSITION_SL);

         double oldTP =
            PositionGetDouble(POSITION_TP);

         if(open <= 0.0)
            continue;

         if(type == POSITION_TYPE_BUY)
         {
            ManageBuy(
               trade,
               ticket,
               identifier,
               sym,
               tick,
               open,
               oldSL,
               oldTP,
               trailDistance,
               minimumDistance,
               point,
               digits
            );
         }
         else if(type == POSITION_TYPE_SELL)
         {
            ManageSell(
               trade,
               ticket,
               identifier,
               sym,
               tick,
               open,
               oldSL,
               oldTP,
               trailDistance,
               minimumDistance,
               point,
               digits
            );
         }
      }
   }

   void CloseAll(CTrade &trade, string sym, long magic)
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(PositionGetString(POSITION_SYMBOL) != sym ||
            PositionGetInteger(POSITION_MAGIC) != magic)
            continue;

         bool closed = trade.PositionClose(ticket);

         uint code = trade.ResultRetcode();

         if(!closed ||
            (code != TRADE_RETCODE_DONE &&
             code != TRADE_RETCODE_DONE_PARTIAL))
         {
            Print(
               "Position close failed. Ticket=",
               ticket,
               " Retcode=",
               code,
               " ",
               trade.ResultRetcodeDescription()
            );
         }
      }
   }
};

#endif
