#ifndef GOLD_RISK_MANAGER
#define GOLD_RISK_MANAGER
#include "MoneyManagement.mqh"
class CRiskManager
{
private: CMoneyManagement money;
public:
 double BaseLot(double equity){return money.BaseLot(equity);}
 int MaxPositions(double e)
 { if(e<4)return 2;if(e<10)return 3;if(e<25)return 5;if(e<50)return 7;if(e<100)return 9;if(e<250)return 12;if(e<500)return 14;if(e<1000)return 16;return 18; }
 double VolumeForPosition(string sym,double equity,int number)
 {
   double v=BaseLot(equity); if(equity>=25)v+=(double)((number-1)/2)*.01;
   return money.NormalizeVolume(sym,v);
 }
 double NormalizeVolume(string sym,double volume){return money.NormalizeVolume(sym,volume);}
 double FitVolumeToMargin(string sym,ENUM_ORDER_TYPE side,double volume,double price,double freeMargin)
 {
   double step=SymbolInfoDouble(sym,SYMBOL_VOLUME_STEP),minv=SymbolInfoDouble(sym,SYMBOL_VOLUME_MIN);
   if(step<=0 || minv<=0 || freeMargin<=0)return 0.0;
   while(volume>=minv-0.00000001)
   {
      double margin=0.0;
      if(OrderCalcMargin(side,sym,volume,price,margin) && margin<=freeMargin*0.80)
      {
         int digits=0; while(digits<8 && MathAbs(step-NormalizeDouble(step,digits))>0.00000001)digits++;
         return NormalizeDouble(volume,digits);
      }
      volume-=step;
   }
   return 0.0;
 }
 bool DrawdownExceeded(double equity,double balance,double limit)
 { if(balance<=0)return false; return ((balance-equity)/balance*100.0)>=limit; }
 bool BuildStops(string sym,ENUM_ORDER_TYPE side,double entry,double volume,int confidence,double &sl,double &tp)
 {
   double point=SymbolInfoDouble(sym,SYMBOL_POINT),ticksize=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE);
   if(point<=0 || ticksize<=0)return false;
   double tickvalue=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
   double vol=volume;
   if(tickvalue<=0 || vol<=0)return false;
   double slMoney=2.0,tpMoney=2.2;
   if(confidence>=8){slMoney*=1.15;tpMoney*=1.15;}else if(confidence>=6){slMoney*=1.08;tpMoney*=1.08;}else if(confidence<=2){slMoney*=.90;tpMoney*=.90;}
   slMoney=MathMax(1.5,MathMin(3.0,slMoney));tpMoney=MathMax(1.8,MathMin(3.5,MathMax(slMoney,tpMoney)));
   double slDist=(slMoney/(tickvalue*vol))*ticksize, tpDist=(tpMoney/(tickvalue*vol))*ticksize;
   long stops=SymbolInfoInteger(sym,SYMBOL_TRADE_STOPS_LEVEL);
   long freeze=SymbolInfoInteger(sym,SYMBOL_TRADE_FREEZE_LEVEL);
   double minDist=(double)MathMax(stops,freeze)*point;
   slDist=MathMax(slDist,minDist+2*point);tpDist=MathMax(tpDist,minDist+2*point);
   if(side==ORDER_TYPE_BUY){sl=NormalizeDouble(entry-slDist,(int)SymbolInfoInteger(sym,SYMBOL_DIGITS));tp=NormalizeDouble(entry+tpDist,(int)SymbolInfoInteger(sym,SYMBOL_DIGITS));}
   else{sl=NormalizeDouble(entry+slDist,(int)SymbolInfoInteger(sym,SYMBOL_DIGITS));tp=NormalizeDouble(entry-tpDist,(int)SymbolInfoInteger(sym,SYMBOL_DIGITS));}
   return true;
 }
};
#endif
