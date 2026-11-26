
#ifndef GOLD_SPREAD_ANALYZER
#define GOLD_SPREAD_ANALYZER

#include "MarketAnalyzer.mqh"

class CSpreadAnalyzer
{
public:

   // Retained for compatibility and market-information purposes.
   // This value is informational only, not an entry restriction.
   double SpreadToATR(string symbol)
   {
      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return 0.0;

      double atr = iATR(symbol, PERIOD_M1, 14);

      if(atr <= 0.0)
         return 0.0;

      return (tick.ask - tick.bid) / atr;
   }

   // No arbitrary spread-to-ATR threshold may reject an original signal.
   // ExecutionManager separately checks that the broker quote is valid.
   bool IsAcceptable(string symbol, double maximumRatio)
   {
      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return false;

      return tick.bid > 0.0 && tick.ask >= tick.bid;
   }
};

#endif
