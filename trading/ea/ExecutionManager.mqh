
#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER

class CExecutionManager
{
public:

   CExecutionManager()
   {
   }

   void Init(string symbol)
   {
      // Symbol validation and broker configuration are handled
      // by BrokerSpecification.mqh.
   }

   void Release()
   {
   }

   bool EntryCostOK(
      string symbol,
      ENUM_ORDER_TYPE side,
      int confidence
   )
   {
      MqlTick tick;

      // A valid current broker quote is required.
      if(!SymbolInfoTick(symbol, tick))
         return false;

      if(tick.bid <= 0.0 || tick.ask <= 0.0)
         return false;

      if(tick.ask < tick.bid)
         return false;

      if(side != ORDER_TYPE_BUY &&
         side != ORDER_TYPE_SELL)
         return false;

      // No arbitrary spread ceiling.
      // No confidence-based spread rejection.
      // No invented movement multiplier.

      return true;
   }
};

#endif
