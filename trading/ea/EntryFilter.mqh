
#ifndef GOLD_ENTRY_FILTER
#define GOLD_ENTRY_FILTER

class CEntryFilter
{
public:

   // Preserve the original signal engine's decision.
   // No additional trend, volatility, spread or candle filter
   // is allowed to veto a valid BUY or SELL signal.
   bool Allowed(
      string symbol,
      ENUM_ORDER_TYPE side,
      bool requireCandle
   )
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
