
#ifndef GOLD_RISK_MANAGER
#define GOLD_RISK_MANAGER

#include "MoneyManagement.mqh"

class CRiskManager
{
private:
   CMoneyManagement money;

   int VolumeDigits(string symbol)
   {
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);

      if(step <= 0.0)
         return 2;

      int digits = 0;

      while(digits < 8 &&
            MathAbs(step - NormalizeDouble(step, digits)) > 0.00000001)
      {
         digits++;
      }

      return digits;
   }

public:

   double BaseLot(double equity)
   {
      return money.BaseLot(equity);
   }

   int MaxPositions(double equity)
   {
      if(equity < 4.0)      return 2;
      if(equity < 10.0)     return 3;
      if(equity < 25.0)     return 5;
      if(equity < 50.0)     return 7;
      if(equity < 100.0)    return 9;
      if(equity < 250.0)    return 12;
      if(equity < 500.0)    return 14;
      if(equity < 1000.0)   return 16;

      return 18;
   }

   double VolumeForPosition(
      string symbol,
      double equity,
      int number
   )
   {
      if(number < 1)
         number = 1;

      double volume = BaseLot(equity);

      if(equity >= 25.0)
      {
         int additionalSteps = (number - 1) / 2;
         volume += (double)additionalSteps * 0.01;
      }

      return money.NormalizeVolume(symbol, volume);
   }

   double NormalizeVolume(string symbol, double volume)
   {
      return money.NormalizeVolume(symbol, volume);
   }

   double FitVolumeToMargin(
      string symbol,
      ENUM_ORDER_TYPE side,
      double volume,
      double price,
      double freeMargin
   )
   {
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);

      if(step <= 0.0 || minimum <= 0.0 ||
         maximum < minimum || freeMargin <= 0.0)
      {
         return 0.0;
      }

      volume = MathMin(volume, maximum);
      volume = MathFloor(volume / step + 0.00000001) * step;

      int digits = VolumeDigits(symbol);

      while(volume >= minimum - 0.00000001)
      {
         double requiredMargin = 0.0;

         if(OrderCalcMargin(
               side,
               symbol,
               volume,
               price,
               requiredMargin
            ))
         {
            if(requiredMargin > 0.0 &&
               requiredMargin <= freeMargin)
            {
               return NormalizeDouble(volume, digits);
            }
         }

         volume -= step;
         volume = NormalizeDouble(volume, digits);
      }

      return 0.0;
   }

   // Compatibility method for older callers.
   bool BuildStops(
      string symbol,
      ENUM_ORDER_TYPE side,
      double entry,
      double volume,
      int confidence,
      double &sl,
      double &tp
   )
   {
      return BuildStops(
         symbol,
         side,
         entry,
         volume,
         confidence,
         0.0,
         0.0,
         1,
         sl,
         tp
      );
   }

   // Original dynamic SL/TP formula.
   //
   // spreadUsd:
   // Actual bid/ask difference expressed in the gold
   // instrument's price units.
   //
   // recentMovement:
   // Absolute price movement from the original
   // three-observation momentum calculation.
   //
   // positionNumber:
   // Number of this position in the account's
   // current managed sequence, starting at 1.

   bool BuildStops(
      string symbol,
      ENUM_ORDER_TYPE side,
      double entry,
      double volume,
      int confidence,
      double spreadUsd,
      double recentMovement,
      int positionNumber,
      double &sl,
      double &tp
   )
   {
      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      double tickSize =
         SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);

      double tickValue =
         SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);

      int digits =
         (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(point <= 0.0 ||
         tickSize <= 0.0 ||
         tickValue <= 0.0 ||
         volume <= 0.0 ||
         entry <= 0.0 ||
         spreadUsd < 0.0 ||
         recentMovement < 0.0)
      {
         return false;
      }

      if(positionNumber < 1)
         positionNumber = 1;

      // Original position-number adjustment.
      double positionAdjustment =
         (double)(positionNumber - 1) * 0.08;

      // Original recent-movement multiplier.
      double movementMultiplier = 1.0;

      if(recentMovement > 0.50)
         movementMultiplier = 1.30;
      else if(recentMovement > 0.25)
         movementMultiplier = 1.15;
      else if(recentMovement > 0.10)
         movementMultiplier = 1.05;

      // Original confidence multiplier.
      double confidenceMultiplier = 1.0;

      if(confidence >= 8)
         confidenceMultiplier = 1.15;
      else if(confidence >= 6)
         confidenceMultiplier = 1.08;
      else if(confidence <= 2)
         confidenceMultiplier = 0.90;

      // Original dynamic monetary distances.
      double slMoney =
         (2.0 + (0.5 * spreadUsd) + positionAdjustment)
         * movementMultiplier;

      double tpMoney =
         (2.2 + (0.3 * spreadUsd) + positionAdjustment)
         * movementMultiplier
         * confidenceMultiplier;

      // Original distance boundaries.
      slMoney = MathMax(1.5, MathMin(3.0, slMoney));

      tpMoney = MathMax(
         1.8,
         MathMin(3.5, MathMax(slMoney, tpMoney))
      );

      // Convert monetary distance into price distance.
      double moneyPerPriceUnit = tickValue * volume;

      if(moneyPerPriceUnit <= 0.0)
         return false;

      double slDistance =
         (slMoney / moneyPerPriceUnit) * tickSize;

      double tpDistance =
         (tpMoney / moneyPerPriceUnit) * tickSize;

      if(slDistance <= 0.0 || tpDistance <= 0.0)
         return false;

      // Respect broker stop and freeze levels.
      long stopLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

      long freezeLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);

      double minimumDistance =
         ((double)MathMax(stopLevel, freezeLevel) + 2.0)
         * point;

      slDistance = MathMax(slDistance, minimumDistance);
      tpDistance = MathMax(tpDistance, minimumDistance);

      if(side == ORDER_TYPE_BUY)
      {
         sl = NormalizeDouble(entry - slDistance, digits);
         tp = NormalizeDouble(entry + tpDistance, digits);

         if(sl >= entry || tp <= entry)
            return false;
      }
      else if(side == ORDER_TYPE_SELL)
      {
         sl = NormalizeDouble(entry + slDistance, digits);
         tp = NormalizeDouble(entry - tpDistance, digits);

         if(sl <= entry || tp >= entry)
            return false;
      }
      else
      {
         return false;
      }

      return true;
   }
};

#endif
