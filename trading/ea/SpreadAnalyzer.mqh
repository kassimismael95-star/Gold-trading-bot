#ifndef GOLD_SPREAD_ANALYZER
#define GOLD_SPREAD_ANALYZER
#include "MarketAnalyzer.mqh"
class CSpreadAnalyzer
{
private: CMarketAnalyzer analyzer;
public:
 double SpreadToATR(string symbol)
 {
   MqlTick tick;if(!SymbolInfoTick(symbol,tick))return 999.0;
   double atr=analyzer.ATR(symbol,PERIOD_M1,14);if(atr<=0)return 999.0;
   return (tick.ask-tick.bid)/atr;
 }
 bool IsAcceptable(string symbol,double maximumRatio)
 { return SpreadToATR(symbol)<=maximumRatio; }
};
#endif
