
#ifndef GOLD_MONEY_MANAGEMENT
#define GOLD_MONEY_MANAGEMENT

class CMoneyManagement
{
public:

   double BaseLot(double equity)
   {
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
      if(equity < 10000) return 1.0;
      if(equity < 25000) return 2.0;

      return 4.0;
   }

   double NormalizeVolume(string symbol, double volume)
   {
      double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      if(step <= 0 || maximum <= 0 || minimum <= 0)
         return 0.0;

      volume = MathMax(minimum, MathMin(maximum, volume));
      volume = MathFloor(volume / step + 0.00000001) * step;

      int digits = 0;

      while(digits < 8 &&
            MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001)
      {
         digits++;
      }

      return NormalizeDouble(volume, digits);
   }
};

#endif
