#ifndef GOLD_ACCOUNT_RISK_MONITOR
#define GOLD_ACCOUNT_RISK_MONITOR
#include "DrawdownManager.mqh"
class CAccountRiskMonitor
{
private: CDrawdownManager monitor;
public:
 bool AccountLimitReached(double equity,double balance,double percent)
 { return monitor.AccountDrawdownExceeded(equity,balance,percent); }
 bool BasketLimitReached(double basketProfit,double lossLimit)
 { return monitor.BasketLossExceeded(basketProfit,lossLimit); }
};
#endif
