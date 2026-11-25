#ifndef GOLD_ADAPTIVE_MANAGER
#define GOLD_ADAPTIVE_MANAGER
class CAdaptiveManager
{
private:
 long accountId;
 int winStreak;
 int lossStreak;
 bool caution;
 double volumeMultiplier;
 string Key(string suffix){return "GoldAdaptive_"+(string)accountId+"_"+suffix;}
 void Persist()
 {
   GlobalVariableSet(Key("wins"),(double)winStreak);
   GlobalVariableSet(Key("losses"),(double)lossStreak);
   GlobalVariableSet(Key("caution"),caution?1.0:0.0);
   GlobalVariableSet(Key("multiplier"),volumeMultiplier);
 }
public:
 CAdaptiveManager(){accountId=0;winStreak=0;lossStreak=0;caution=false;volumeMultiplier=1.0;}
 void Init(long id)
 {
   accountId=id;
   if(GlobalVariableCheck(Key("wins")))winStreak=(int)GlobalVariableGet(Key("wins"));
   if(GlobalVariableCheck(Key("losses")))lossStreak=(int)GlobalVariableGet(Key("losses"));
   if(GlobalVariableCheck(Key("caution")))caution=GlobalVariableGet(Key("caution"))>0.5;
   if(GlobalVariableCheck(Key("multiplier")))volumeMultiplier=GlobalVariableGet(Key("multiplier"));
   volumeMultiplier=MathMax(0.50,MathMin(1.25,volumeMultiplier));
 }
 void RecordOutcome(long id,ulong dealId,double pnl)
 {
   string marker="GoldAdaptiveDeal_"+(string)id+"_"+(string)dealId;
   if(GlobalVariableCheck(marker))return;
   GlobalVariableSet(marker,1.0);
   if(pnl>0.0)
   {
      winStreak++; lossStreak=0;
      if(winStreak>=3){volumeMultiplier=MathMin(1.25,volumeMultiplier+0.05);winStreak=0;caution=false;}
   }
   else if(pnl<0.0)
   {
      lossStreak++; winStreak=0; caution=true;
      if(lossStreak>=2){volumeMultiplier=MathMax(0.50,volumeMultiplier-0.10);lossStreak=0;}
   }
   Persist();
 }
 double VolumeMultiplier(){return volumeMultiplier;}
 int MinimumConfidence(){return caution?5:4;}
};
#endif
