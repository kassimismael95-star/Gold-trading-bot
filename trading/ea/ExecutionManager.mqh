#ifndef GOLD_EXECUTION_MANAGER
#define GOLD_EXECUTION_MANAGER
class CExecutionManager
{
private:
 int atrHandle; string atrSymbol;
public:
 CExecutionManager(){atrHandle=INVALID_HANDLE;atrSymbol="";}
 void Init(string sym)
 {
   if(atrHandle!=INVALID_HANDLE)IndicatorRelease(atrHandle);
   atrSymbol=sym; atrHandle=iATR(sym,PERIOD_M1,14);
 }
 void Release()
 { if(atrHandle!=INVALID_HANDLE){IndicatorRelease(atrHandle);atrHandle=INVALID_HANDLE;} }
 bool EntryCostOK(string sym,ENUM_ORDER_TYPE side,int confidence)
 {
   MqlTick tick;if(!SymbolInfoTick(sym,tick))return false;
   double spread=tick.ask-tick.bid;
   if(atrHandle==INVALID_HANDLE || atrSymbol!=sym)return false;
   double buffer[]; ArraySetAsSeries(buffer,true);
   if(CopyBuffer(atrHandle,0,0,1,buffer)<=0)return false;
   double atr=buffer[0];
   if(atr<=0)return false;
   double expectedMove=atr*(confidence>=8?1.8:confidence>=6?1.4:1.1);
   if(expectedMove<=0)return false;
   return spread/expectedMove<=0.30;
 }
};
#endif
