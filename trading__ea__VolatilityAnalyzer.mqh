#ifndef GOLD_VOLATILITY_ANALYZER
#define GOLD_VOLATILITY_ANALYZER
#include "MarketAnalyzer.mqh"
class CVolatilityAnalyzer
{
private: CMarketAnalyzer analyzer;
public:
 double ATRRatio(string symbol)
 {
   MqlTick tick;if(!SymbolInfoTick(symbol,tick))return 0.0;
   double mid=(tick.bid+tick.ask)/2.0;if(mid<=0)return 0.0;
   double atr=analyzer.ATR(symbol,PERIOD_M1,14);if(atr<=0)return 0.0;
   return atr/mid;
 }
 bool IsValid(string symbol,double minimumRatio,double maximumRatio)
 {
   double ratio=ATRRatio(symbol);
   return ratio>=minimumRatio && ratio<=maximumRatio;
 }
};
#endif
