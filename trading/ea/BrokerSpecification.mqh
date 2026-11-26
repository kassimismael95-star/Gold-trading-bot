
#ifndef GOLD_BROKER_SPECIFICATION
#define GOLD_BROKER_SPECIFICATION

class CBrokerSpecification
{
public:

   // Confirm that the symbol has usable broker trading specifications.
   bool Validate(string symbol)
   {
      if(symbol == "")
         return false;

      if(!SymbolSelect(symbol, true))
         return false;

      long tradeMode = 0;

      if(!SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE, tradeMode))
         return false;

      double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

      double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      return tradeMode != SYMBOL_TRADE_MODE_DISABLED &&
             tickSize > 0.0 &&
             tickValue > 0.0 &&
             point > 0.0 &&
             minimum > 0.0 &&
             maximum >= minimum &&
             step > 0.0 &&
             digits >= 0;
   }

   // Check whether the broker currently permits the requested direction.
   bool AllowsDirection(string symbol, ENUM_ORDER_TYPE orderType)
   {
      long mode = 0;

      if(!SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE, mode))
         return false;

      if(mode == SYMBOL_TRADE_MODE_DISABLED ||
         mode == SYMBOL_TRADE_MODE_CLOSEONLY)
         return false;

      if(orderType == ORDER_TYPE_BUY)
         return mode == SYMBOL_TRADE_MODE_FULL ||
                mode == SYMBOL_TRADE_MODE_LONGONLY;

      if(orderType == ORDER_TYPE_SELL)
         return mode == SYMBOL_TRADE_MODE_FULL ||
                mode == SYMBOL_TRADE_MODE_SHORTONLY;

      return false;
   }

   // Broker minimum stop distance, including a small point allowance.
   double MinimumStopDistance(string symbol)
   {
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

      if(point <= 0.0)
         return 0.0;

      long stops = SymbolInfoInteger(
         symbol,
         SYMBOL_TRADE_STOPS_LEVEL
      );

      long freeze = SymbolInfoInteger(
         symbol,
         SYMBOL_TRADE_FREEZE_LEVEL
      );

      long required = stops > freeze ? stops : freeze;

      return ((double)required + 2.0) * point;
   }

   // Normalize volume down to a valid broker volume step.
   // It never rounds a requested volume upward.
   double NormalizeVolume(string symbol, double requestedVolume)
   {
      if(requestedVolume <= 0.0)
         return 0.0;

      double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      if(minimum <= 0.0 || maximum < minimum || step <= 0.0)
         return 0.0;

      if(requestedVolume < minimum)
         return 0.0;

      double capped = MathMin(requestedVolume, maximum);
      double steps = MathFloor((capped - minimum) / step + 1e-9);

      double volume = minimum + steps * step;

      int precision = 0;
      double testStep = step;

      while(precision < 8 &&
            MathAbs(testStep - MathRound(testStep)) > 1e-8)
      {
         testStep *= 10.0;
         precision++;
      }

      volume = NormalizeDouble(volume, precision);

      if(volume < minimum || volume > maximum)
         return 0.0;

      return volume;
   }

   // Normalize a price to the symbol's valid tick size and digits.
   double NormalizePrice(string symbol, double price)
   {
      double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(tickSize <= 0.0 || price <= 0.0)
         return 0.0;

      double normalized = MathRound(price / tickSize) * tickSize;

      return NormalizeDouble(normalized, digits);
   }

   // Return the broker's minimum permitted trade volume.
   double MinimumVolume(string symbol)
   {
      return SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   }

   // Return the broker's maximum permitted trade volume.
   double MaximumVolume(string symbol)
   {
      return SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   }

   // Return the broker's volume increment.
   double VolumeStep(string symbol)
   {
      return SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   }
};

#endif
