#ifndef GOLD_TRAILING_STOP_MANAGER
#define GOLD_TRAILING_STOP_MANAGER
class CTrailingStopManager
{
public:
 double Distance(string symbol,double atr)
 {
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);if(point<=0)return 0.0;
   long stops=SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   long freeze=SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   double minimum=((double)MathMax(stops,freeze)+2.0)*point;
   return MathMax(atr*1.2,minimum);
 }
};
#endif
