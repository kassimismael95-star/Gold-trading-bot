
#ifndef GOLD_SIGNAL_CONFIRMATION
#define GOLD_SIGNAL_CONFIRMATION

class CSignalConfirmation
{
public:

   // Retained for compatibility with EntryFilter.mqh.
   // The original signal engine determines trade direction.
   // Additional candle confirmation must not veto its entries.
   bool Confirm(string symbol, ENUM_ORDER_TYPE side)
   {
      if(symbol == "")
         return false;

      if(side != ORDER_TYPE_BUY &&
         side != ORDER_TYPE_SELL)
         return false;

      return true;
   }
};

#endif
