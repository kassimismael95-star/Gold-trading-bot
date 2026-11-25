#ifndef GOLD_POSITION_MANAGER
#define GOLD_POSITION_MANAGER
#include <Trade/Trade.mqh>
#include "TrailingStopManager.mqh"
class CPositionManager
{
private: CTrailingStopManager trailing;
public:
 void Manage(CTrade &trade,string sym,long magic,CSignalEngine &signals)
 {
   MqlTick tick; if(!SymbolInfoTick(sym,tick)) return;
   double point=SymbolInfoDouble(sym,SYMBOL_POINT);
   double tickSize=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE);
   double tickValue=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
   int digits=(int)SymbolInfoInteger(sym,SYMBOL_DIGITS);
   if(point<=0 || tickSize<=0 || tickValue<=0) return;
   MqlRates rates[]; ArraySetAsSeries(rates,true);
   int copied=CopyRates(sym,PERIOD_M1,0,15,rates);
   double atr=0.0;
   if(copied>1)
   {
      for(int r=1;r<copied;r++) atr+=MathMax(0.0,rates[r].high-rates[r].low);
      atr/=((double)copied-1.0);
   }
   double minDistance=trailing.Distance(sym,0.0);
   double trailDistance=trailing.Distance(sym,atr);
   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      ulong ticket=PositionGetTicket(i); if(ticket==0)continue;
      if(PositionGetString(POSITION_SYMBOL)!=sym || PositionGetInteger(POSITION_MAGIC)!=magic)continue;
      long type=PositionGetInteger(POSITION_TYPE);
      double open=PositionGetDouble(POSITION_PRICE_OPEN);
      double sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP);
      double volume=PositionGetDouble(POSITION_VOLUME);
      double profit=PositionGetDouble(POSITION_PROFIT);
      double valuePerPoint=tickValue*(point/tickSize)*volume;
      double trigger=MathMax(1.0,valuePerPoint*8.0);
      if(profit<trigger) continue;
      if(type==POSITION_TYPE_BUY)
      {
         double candidate=MathMax(open+2.0*point,tick.bid-trailDistance);
         if(candidate>=tick.bid-minDistance) continue;
         candidate=NormalizeDouble(candidate,digits);
         if(sl==0.0 || candidate>sl+point) trade.PositionModify(ticket,candidate,tp);
      }
      else if(type==POSITION_TYPE_SELL)
      {
         double candidate=MathMin(open-2.0*point,tick.ask+trailDistance);
         if(candidate<=tick.ask+minDistance) continue;
         candidate=NormalizeDouble(candidate,digits);
         if(sl==0.0 || candidate<sl-point) trade.PositionModify(ticket,candidate,tp);
      }
   }
 }
 void CloseAll(CTrade &trade,string sym,long magic)
 {
   for(int i=PositionsTotal()-1;i>=0;i--)
   { ulong t=PositionGetTicket(i); if(t>0 && PositionGetString(POSITION_SYMBOL)==sym && PositionGetInteger(POSITION_MAGIC)==magic) trade.PositionClose(t); }
 }
};
#endif
