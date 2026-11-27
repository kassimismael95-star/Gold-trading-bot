
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

   // Preserve the original equity-based lot tier.
   // Do not increase lot size because of intelligence,
   // confidence or the number of open positions.
   double VolumeForPosition(
      string symbol,
      double equity,
      int number
   )
   {
      return money.NormalizeVolume(
         symbol,
         BaseLot(equity)
      );
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

   bool DrawdownExceeded(
      double equity,
      double balance,
      double limit
   )
   {
      if(balance <= 0.0 || limit <= 0.0)
         return false;

      double drawdown =
         ((balance - equity) / balance) * 100.0;

      return drawdown >= limit;
   }

   // Compatibility overload for existing callers.
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

   // Original Python dynamic TP/SL formula.
   //
   // spreadPips is converted using the original
   // spread_usd = current_spread_pips * 0.10.
   //
   // recentMovement is the original three-tick movement.
   // positionNumber starts at 1.

   bool BuildStops(
      string symbol,
      ENUM_ORDER_TYPE side,
      double entry,
      double volume,
      int confidence,
      double spreadPips,
      double recentMovement,
      int positionNumber,
      double &sl,
      double &tp
   )
   {
      double point =
         SymbolInfoDouble(symbol, SYMBOL_POINT);

      int digits =
         (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);

      if(point <= 0.0 ||
         entry <= 0.0 ||
         volume <= 0.0 ||
         spreadPips < 0.0 ||
         recentMovement < 0.0)
      {
         return false;
      }

      if(positionNumber < 1)
         positionNumber = 1;

      // Original spread conversion.
      double spreadUsd = spreadPips * 0.10;

      // Original movement multiplier.
      double movementMultiplier = 1.00;

      if(recentMovement > 0.50)
         movementMultiplier = 1.30;
      else if(recentMovement > 0.25)
         movementMultiplier = 1.15;
      else if(recentMovement > 0.10)
         movementMultiplier = 1.05;

      // Original confidence multiplier.
      double confidenceMultiplier = 1.00;

      if(confidence >= 8)
         confidenceMultiplier = 1.15;
      else if(confidence >= 6)
         confidenceMultiplier = 1.08;
      else if(confidence <= 2)
         confidenceMultiplier = 0.90;

      // Original position-number adjustment.
      double positionAdjustment =
         (double)(positionNumber - 1) * 0.08;

      // Original stop-loss distance.
      double slDistance =
         (2.00 + spreadUsd * 0.50 + positionAdjustment)
         * movementMultiplier;

      // Original take-profit distance.
      double tpDistance =
         (2.20 + spreadUsd * 0.30 + positionAdjustment)
         * movementMultiplier
         * confidenceMultiplier;

      // Original SL boundaries.
      slDistance = MathMax(
         1.50,
         MathMin(3.00, slDistance)
      );

      // Original TP boundaries.
      tpDistance = MathMax(
         1.80,
         MathMin(3.50, tpDistance)
      );

      // Original rule: TP must be at least as far as SL.
      tpDistance = MathMax(tpDistance, slDistance);

      // Broker minimum stop distance.
      long stopLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

      long freezeLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);

      double minimumDistance =
         ((double)MathMax(stopLevel, freezeLevel) + 2.0)
         * point;

      // Broker restrictions take priority if their
      // minimum distance exceeds the strategy distance.
      slDistance = MathMax(slDistance, minimumDistance);
      tpDistance = MathMax(tpDistance, minimumDistance);

      if(side == ORDER_TYPE_BUY)
      {
         sl = NormalizeDouble(entry - slDistance, digits);
         tp = NormalizeDouble(entry + tpDistance, digits);

         return (sl < entry && tp > entry);
      }

      if(side == ORDER_TYPE_SELL)
      {
         sl = NormalizeDouble(entry + slDistance, digits);
         tp = NormalizeDouble(entry - tpDistance, digits);

         return (sl > entry && tp < entry);
      }

      return false;
   }
};

#endif
