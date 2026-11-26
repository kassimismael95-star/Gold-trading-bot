
#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER

class CExecutionManager
{
public:
   CExecutionManager()
   {
   }

   void Init(string sym)
   {
      // No arbitrary spread ratio or confidence-based movement rule.
      // The EA initializes and validates the broker symbol separately.
   }

   void Release()
   {
   }

   bool EntryCostOK(string sym, ENUM_ORDER_TYPE side, int confidence)
   {
      MqlTick tick;

      // Validate that the broker has supplied a usable quote.
      if(!SymbolInfoTick(sym, tick))
         return false;

      if(tick.bid <= 0.0 || tick.ask <= 0.0)
         return false;

      if(tick.ask < tick.bid)
         return false;

      if(side != ORDER_TYPE_BUY && side != ORDER_TYPE_SELL)
         return false;

      /*
         Removed from the original:
         - fixed spread-to-expected-move ratio
         - invented ATR movement multipliers
         - confidence-based spread rejection

         This method does not impose an arbitrary spread ceiling.
         Broker execution validity, your strategy, position sizing,
         account risk, and broker margin requirements remain handled
         by their existing modules.
      */

      return true;
   }
};

#endif
