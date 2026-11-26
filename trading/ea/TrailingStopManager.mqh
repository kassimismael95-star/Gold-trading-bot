
#ifndef GOLD_TRAILING_STOP_MANAGER
#define GOLD_TRAILING_STOP_MANAGER

class CTrailingStopManager
{
private:

   double MinimumDistance(string symbol)
   {
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);

      if(point <= 0.0)
         return 0.0;

      long stops =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

      long freeze =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);

      return ((double)MathMax(stops, freeze) + 2.0) * point;
   }

public:

   // Compatibility method used by PositionManager.
   double Distance(string symbol, double atr)
   {
      double minimum = MinimumDistance(symbol);

      if(minimum <= 0.0)
         return 0.0;

      if(atr <= 0.0)
         return minimum;

      return MathMax(atr * 1.2, minimum);
   }

   // Volatility-aware trailing distance.
   double AdaptiveDistance(
      string symbol,
      double atr,
      double volatilityRatio
   )
   {
      double minimum = MinimumDistance(symbol);

      if(minimum <= 0.0)
         return 0.0;

      if(atr <= 0.0)
         return minimum;

      double multiplier = 1.2;

      if(volatilityRatio >= 1.5)
         multiplier = 1.6;
      else if(volatilityRatio >= 1.2)
         multiplier = 1.4;
      else if(volatilityRatio <= 0.7)
         multiplier = 0.9;

      double distance = atr * multiplier;

      return MathMax(distance, minimum);
   }

   // Calculate a candidate stop without allowing it to move
   // in the direction that increases the original risk.
   double ImprovedStop(
      ENUM_POSITION_TYPE direction,
      double currentPrice,
      double currentStop,
      double distance,
      double point,
      int digits
   )
   {
      if(currentPrice <= 0.0 ||
         distance <= 0.0 ||
         point <= 0.0)
      {
         return 0.0;
      }

      double candidate = 0.0;

      if(direction == POSITION_TYPE_BUY)
      {
         candidate = currentPrice - distance;

         if(currentStop > 0.0 &&
            candidate <= currentStop + point)
         {
            return 0.0;
         }
      }
      else if(direction == POSITION_TYPE_SELL)
      {
         candidate = currentPrice + distance;

         if(currentStop > 0.0 &&
            candidate >= currentStop - point)
         {
            return 0.0;
         }
      }
      else
      {
         return 0.0;
      }

      return NormalizeDouble(candidate, digits);
   }
};

#endif
