#ifndef GOLD_BROKER_SPECIFICATION
#define GOLD_BROKER_SPECIFICATION
class CBrokerSpecification
{
public:
 bool Validate(string symbol)
 {
   if(!SymbolSelect(symbol,true))return false;
   long mode=SymbolInfoInteger(symbol,SYMBOL_TRADE_MODE);
   double tickSize=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   double tickValue=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE);
   double minimum=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   double maximum=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   return mode!=SYMBOL_TRADE_MODE_DISABLED && tickSize>0 && tickValue>0 &&
      minimum>0 && maximum>=minimum && step>0 && digits>=0;
 }
 double MinimumStopDistance(string symbol)
 {
   double point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   long stops=SymbolInfoInteger(symbol,SYMBOL_TRADE_STOPS_LEVEL);
   long freeze=SymbolInfoInteger(symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   if(point<=0)return 0.0;
   return ((double)MathMax(stops,freeze)+2.0)*point;
 }
};
#endif
