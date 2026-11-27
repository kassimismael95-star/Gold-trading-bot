
#ifndef GOLD_TRAILING_STOP_MANAGER
#define GOLD_TRAILING_STOP_MANAGER

class CTrailingStopManager
{
private:

   double Clamp(
      double value,
      double minimum,
      double maximum
   )
   {
      return MathMax(
         minimum,
         MathMin(maximum, value)
      );
   }

   double MinimumDistance(string symbol)
   {
      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      if(point <= 0.0)
         return 0.0;

      long stops =
         SymbolInfoInteger(
            symbol,
            SYMBOL_TRADE_STOPS_LEVEL
         );

      long freeze =
         SymbolInfoInteger(
            symbol,
            SYMBOL_TRADE_FREEZE_LEVEL
         );

      return (MathMax(stops, freeze) + 2.0) * point;
   }

   double NormalizePrice(
      string symbol,
      double price
   )
   {
      int digits =
         (int)SymbolInfoInteger(
            symbol,
            SYMBOL_DIGITS
         );

      return NormalizeDouble(price, digits);
   }

public:

   // Default adaptive trailing distance.
   double Distance(
      string symbol,
      double atr
   )
   {
      if(symbol == "" || atr <= 0.0)
         return 0.0;

      double distance = atr * 1.50;

      double minimum =
         MinimumDistance(symbol);

      if(minimum > 0.0)
         distance = MathMax(distance, minimum);

      return distance;
   }

   // Adjust trailing distance to changing volatility.
   double AdaptiveDistance(
      string symbol,
      double atr,
      double volatilityRatio
   )
   {
      if(
         symbol == "" ||
         atr <= 0.0 ||
         volatilityRatio <= 0.0
      )
      {
         return 0.0;
      }

      double multiplier = 1.50;

      if(volatilityRatio >= 1.80)
         multiplier = 2.00;
      else if(volatilityRatio >= 1.35)
         multiplier = 1.75;
      else if(volatilityRatio <= 0.65)
         multiplier = 1.15;
      else if(volatilityRatio <= 0.85)
         multiplier = 1.30;

      double distance = atr * multiplier;

      double minimum =
         MinimumDistance(symbol);

      if(minimum > 0.0)
         distance = MathMax(distance, minimum);

      return distance;
   }

   // Calculate a candidate stop.
   // This method never intentionally loosens an existing stop.
   double ImprovedStop(
      ENUM_POSITION_TYPE direction,
      double currentPrice,
      double currentSL,
      double distance,
      double point,
      int digits
   )
   {
      if(
         currentPrice <= 0.0 ||
         distance <= 0.0 ||
         point <= 0.0
      )
      {
         return 0.0;
      }

      double candidate = 0.0;

      if(direction == POSITION_TYPE_BUY)
      {
         candidate =
            currentPrice - distance;

         if(
            currentSL > 0.0 &&
            candidate <= currentSL + point
         )
         {
            return 0.0;
         }
      }
      else if(direction == POSITION_TYPE_SELL)
      {
         candidate =
            currentPrice + distance;

         if(
            currentSL > 0.0 &&
            candidate >= currentSL - point
         )
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

   // Calculate a breakeven protection level with a small
   // optional price cushion.
   double BreakevenStop(
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double cushion
   )
   {
      if(entryPrice <= 0.0 || cushion < 0.0)
         return 0.0;

      if(direction == POSITION_TYPE_BUY)
         return entryPrice + cushion;

      if(direction == POSITION_TYPE_SELL)
         return entryPrice - cushion;

      return 0.0;
   }

   // Calculate a profit-locking level in price units.
   double ProfitLockStop(
      ENUM_POSITION_TYPE direction,
      double entryPrice,
      double initialRisk,
      double lockedR
   )
   {
      if(
         entryPrice <= 0.0 ||
         initialRisk <= 0.0 ||
         lockedR < 0.0
      )
      {
         return 0.0;
      }

      if(direction == POSITION_TYPE_BUY)
      {
         return entryPrice +
                initialRisk * lockedR;
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return entryPrice -
                initialRisk * lockedR;
      }

      return 0.0;
   }

   // Choose a more protective candidate without ever
   // moving an existing stop in the wrong direction.
   double SelectMoreProtectiveStop(
      ENUM_POSITION_TYPE direction,
      double existingSL,
      double candidateSL,
      int digits
   )
   {
      if(candidateSL <= 0.0)
         return existingSL;

      if(existingSL <= 0.0)
         return NormalizeDouble(candidateSL, digits);

      if(direction == POSITION_TYPE_BUY)
      {
         return NormalizeDouble(
            MathMax(existingSL, candidateSL),
            digits
         );
      }

      if(direction == POSITION_TYPE_SELL)
      {
         return NormalizeDouble(
            MathMin(existingSL, candidateSL),
            digits
         );
      }

      return existingSL;
   }
};

#endif
