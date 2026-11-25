#ifndef GOLD_PROFIT_MANAGER
#define GOLD_PROFIT_MANAGER
#include "BasketManager.mqh"
class CProfitManager
{
private: CBasketManager basket;
public:
 double BasketProfit(string symbol,long magic){return basket.Profit(symbol,magic);}
 bool TargetReached(double profit,double target){return target>0.0 && profit>=target;}
};
#endif
