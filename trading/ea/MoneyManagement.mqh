
#ifndef GOLD_MONEY_MANAGEMENT
#define GOLD_MONEY_MANAGEMENT

class CMoneyManagement
{
private:

   int VolumeDigits(double step)
   {
      int digits = 0;

      while(digits < 8 &&
            MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001)
      {
         digits++;
      }

      return digits;
   }

public:

   // Original equity-based lot tiers preserved.
   double BaseLot(double equity)
   {
      if(!MathIsValidNumber(equity) || equity <= 0.0)
         return 0.0;

      if(equity < 4)     return 0.01;
      if(equity < 10)    return 0.01;
      if(equity < 25)    return 0.02;
      if(equity < 50)    return 0.03;
      if(equity < 100)   return 0.04;
      if(equity < 250)   return 0.06;
      if(equity < 500)   return 0.10;
      if(equity < 1000)  return 0.20;
      if(equity < 2000)  return 0.35;
      if(equity < 5000)  return 0.60;
      if(equity < 10000) return 1.00;
      if(equity < 25000) return 2.00;

      return 4.00;
   }

   // Normalize volume using the broker's symbol specification.
   // Returns zero when valid volume cannot be established.
   double NormalizeVolume(string symbol, double volume)
   {
      if(StringLen(symbol) <= 0)
         return 0.0;

      if(!MathIsValidNumber(volume) || volume <= 0.0)
         return 0.0;

      double minimum = 0.0;
      double maximum = 0.0;
      double step    = 0.0;

      if(!SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN, minimum))
         return 0.0;

      if(!SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX, maximum))
         return 0.0;

      if(!SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP, step))
         return 0.0;

      if(!MathIsValidNumber(minimum) ||
         !MathIsValidNumber(maximum) ||
         !MathIsValidNumber(step))
      {
         return 0.0;
      }

      if(minimum <= 0.0 ||
         maximum < minimum ||
         step <= 0.0)
      {
         return 0.0;
      }

      // The broker's minimum, maximum and step must permit
      // at least one valid trading volume.
      long minimumUnits = (long)MathCeil(minimum / step - 0.00000001);
      long maximumUnits = (long)MathFloor(maximum / step + 0.00000001);

      if(minimumUnits <= 0 || maximumUnits < minimumUnits)
         return 0.0;

      // Never round upward beyond the requested lot size.
      long requestedUnits = (long)MathFloor(volume / step + 0.00000001);

      if(requestedUnits < minimumUnits)
         requestedUnits = minimumUnits;

      if(requestedUnits > maximumUnits)
         requestedUnits = maximumUnits;

      double normalized = (double)requestedUnits * step;

      int digits = VolumeDigits(step);

      normalized = NormalizeDouble(normalized, digits);

      // Final broker-limit validation.
      if(normalized < minimum - 0.00000001 ||
         normalized > maximum + 0.00000001)
      {
         return 0.0;
      }

      // Verify the normalized volume is on the broker's step.
      double stepUnits = normalized / step;

      if(MathAbs(stepUnits - MathRound(stepUnits)) > 0.000001)
         return 0.0;

      return normalized;
   }
};

#endif
