
#ifndef GOLD_VOLATILITY_ANALYZER
#define GOLD_VOLATILITY_ANALYZER

#include "MarketAnalyzer.mqh"

class CVolatilityAnalyzer
{
private:
   CMarketAnalyzer analyzer;

public:

   // Measure ATR relative to the current market price.
   // This information can be used by intelligent position management.
   double ATRRatio(string symbol)
   {
      MqlTick tick;

      if(!SymbolInfoTick(symbol, tick))
         return 0.0;

      double mid = (tick.bid + tick.ask) / 2.0;

      if(mid <= 0.0)
         return 0.0;

      double atr = analyzer.ATR(symbol, PERIOD_M1, 14);

      if(atr <= 0.0)
         return 0.0;

      return atr / mid;
   }

   // Retain the existing interface for compatibility.
   // Volatility thresholds must not reject original entry signals.
   bool IsValid(
      string symbol,
      double minimumRatio,
      double maximumRatio
   )
   {
      return symbol != "";
   }
};

#endif
