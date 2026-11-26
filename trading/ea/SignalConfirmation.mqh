#ifndef GOLD_SIGNAL_CONFIRMATION
#define GOLD_SIGNAL_CONFIRMATION
class CSignalConfirmation
{
public:
 bool Confirm(string symbol,ENUM_ORDER_TYPE side)
 {
   MqlRates bars[]; ArraySetAsSeries(bars,true);
   if(CopyRates(symbol,PERIOD_M1,1,2,bars)!=2)return false;
   if(side==ORDER_TYPE_BUY)
      return bars[0].close>bars[0].open && bars[1].close>bars[1].open;
   if(side==ORDER_TYPE_SELL)
      return bars[0].close<bars[0].open && bars[1].close<bars[1].open;
   return false;
 }
};
#endif
