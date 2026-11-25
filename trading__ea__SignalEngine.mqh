#ifndef GOLD_SIGNAL_ENGINE
#define GOLD_SIGNAL_ENGINE
class CSignalEngine
{
private:
 double prices[20]; int count; int next;
public:
 CSignalEngine(){count=0;next=0;ArrayInitialize(prices,0);}
 void Observe(double bid,double ask)
 {
   double mid=(bid+ask)/2.0; if(mid<=0)return;
   prices[next]=mid; next=(next+1)%20; if(count<20)count++;
 }
 bool GetSignal(ENUM_ORDER_TYPE &side,int &confidence)
 {
   if(count<5)return false;
   int newest=(next-1+20)%20,third=(next-3+20)%20,oldest=(next-count+20)%20;
   double shortMove=prices[newest]-prices[third],fullMove=prices[newest]-prices[oldest];
   if(shortMove==0 || fullMove==0 || shortMove*fullMove<=0)return false;
   side=shortMove>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
   double ratio=MathAbs(shortMove)/(MathAbs(fullMove)+0.0000001);
   confidence=(int)MathMin(10,4+ratio*5);
   return confidence>=4;
 }
};
#endif
