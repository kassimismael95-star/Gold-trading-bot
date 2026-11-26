
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

   // Original equity-based lot calculation.
   double BaseLot(double equity)
   {
      return money.BaseLot(equity);
   }

   // Original maximum-position tiers.
   // This signature is retained for compatibility with the current EA.
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

   // Confidence-aware version of the original position tiers.
   // Connect this overload when GoldScalperEA.mq5 is updated.
   int MaxPositions(double equity, int confidence)
   {
      if(equity < 4.0)
         return (confidence >= 7 ? 2 : 1);

      if(equity < 10.0)
         return (confidence >= 6 ? 3 : 2);

      if(equity < 25.0)
         return (confidence >= 7 ? 5 : 3);

      if(equity < 50.0)
         return (confidence >= 6 ? 7 : 5);

      if(equity < 100.0)
         return (confidence >= 6 ? 9 : 7);

      if(equity < 250.0)
         return (confidence >= 6 ? 12 : 9);

      if(equity < 500.0)
         return (confidence >= 6 ? 14 : 12);

      if(equity < 1000.0)
         return (confidence >= 6 ? 16 : 14);

      if(equity < 2000.0)
         return (confidence >= 6 ? 18 : 16);

      return 18;
   }

   // Original add-position sizing:
   // Base equity tier plus 0.01 for each pair of additional positions
   // when equity is at least 25.
   double VolumeForPosition(string symbol, double equity, int number)
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

   // Check the broker's actual margin requirement before an order.
   // No arbitrary fixed 20% free-margin reserve is imposed here.
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

   // Retained for compatibility with existing callers.
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

   // Calculate broker-compatible initial SL and TP.
   // The monetary distances are converted using the broker's
   // actual tick value, tick size and trade volume.
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
         entry <= 0.0)
      {
         return false;
      }

      // Original base monetary stop and target.
      double slMoney = 2.0;
      double tpMoney = 2.2;

      // Original confidence adjustments.
      if(confidence >= 8)
      {
         slMoney *= 1.15;
         tpMoney *= 1.15;
      }
      else if(confidence >= 6)
      {
         slMoney *= 1.08;
         tpMoney *= 1.08;
      }
      else if(confidence <= 2)
      {
         slMoney *= 0.90;
         tpMoney *= 0.90;
      }

      // Preserve the original distance boundaries.
      slMoney = MathMax(1.5, MathMin(3.0, slMoney));

      tpMoney = MathMax(
         1.8,
         MathMin(3.5, MathMax(slMoney, tpMoney))
      );

      double moneyPerPriceUnit = tickValue * volume;

      if(moneyPerPriceUnit <= 0.0)
         return false;

      double slDistance =
         (slMoney / moneyPerPriceUnit) * tickSize;

      double tpDistance =
         (tpMoney / moneyPerPriceUnit) * tickSize;

      // Respect the broker's minimum stop and freeze distances.
      long stopLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);

      long freezeLevel =
         SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);

      double minimumDistance =
         ((double)MathMax(stopLevel, freezeLevel) + 2.0) * point;

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
