#ifndef GOLD_DRAWDOWN_MANAGER
#define GOLD_DRAWDOWN_MANAGER
class CDrawdownManager
{
public:
 bool AccountDrawdownExceeded(double equity,double balance,double limitPercent)
 {
   if(balance<=0.0 || limitPercent<=0.0)return false;
   return ((balance-equity)/balance*100.0)>=limitPercent;
 }
 bool BasketLossExceeded(double basketProfit,double maxLossCurrency)
 {
   return maxLossCurrency>0.0 && basketProfit<=-maxLossCurrency;
 }
};
#endif
