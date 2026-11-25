#ifndef GOLD_TREND_DETECTOR
#define GOLD_TREND_DETECTOR
#include "MarketAnalyzer.mqh"
class CTrendDetector
{
private: CMarketAnalyzer analyzer;
public:
 int Direction(string symbol){return analyzer.Trend(symbol,PERIOD_M1);}
 bool Matches(string symbol,ENUM_ORDER_TYPE side)
 {
   int direction=Direction(symbol);
   if(side==ORDER_TYPE_BUY)return direction>0;
   if(side==ORDER_TYPE_SELL)return direction<0;
   return false;
 }
};
#endif
