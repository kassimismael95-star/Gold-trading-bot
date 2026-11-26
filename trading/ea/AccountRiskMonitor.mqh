
#ifndef GOLD_ACCOUNT_RISK_MONITOR
#define GOLD_ACCOUNT_RISK_MONITOR

class CAccountRiskMonitor
{
public:

   // Fixed percentage drawdown shutdown is intentionally disabled.
   // Open positions must be managed individually by the intelligence
   // supervisor instead of being closed by an arbitrary account threshold.
   bool AccountLimitReached(
      double equity,
      double balance,
      double percent
   )
   {
      return false;
   }

   // Fixed basket-loss shutdown is intentionally disabled.
   // Each broker-confirmed position is managed independently.
   bool BasketLimitReached(
      double basketProfit,
      double lossLimit
   )
   {
      return false;
   }
};

#endif
