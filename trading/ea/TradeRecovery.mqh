
#ifndef GOLD_TRADE_RECOVERY
#define GOLD_TRADE_RECOVERY

class CTradeRecovery
{
public:

   string EntryBarKey(long accountId)
   {
      return "GoldLastEntryBar_" + (string)accountId;
   }

   datetime LastEntryBar(long accountId)
   {
      string key = EntryBarKey(accountId);

      return GlobalVariableCheck(key)
         ? (datetime)GlobalVariableGet(key)
         : 0;
   }

   void RecordEntry(long accountId, datetime barTime)
   {
      if(barTime > 0)
      {
         GlobalVariableSet(
            EntryBarKey(accountId),
            (double)barTime
         );
      }
   }

   bool RestartDuplicateBlock(long accountId, datetime currentBar)
   {
      datetime previous = LastEntryBar(accountId);

      return currentBar > 0 && previous == currentBar;
   }
};

#endif
