
#ifndef GOLD_ENTRY_MANAGER
#define GOLD_ENTRY_MANAGER

class CEntryManager
{
public:

   CEntryManager()
   {
   }

   // Original entry authorization.
   // The intelligence supervisor must not filter or delay entries.
   bool CanEnter(
      int currentPositions,
      int maximumPositions,
      bool enabled,
      bool emergency,
      bool riskLocked
   )
   {
      // Manual start/stop and emergency controls remain authoritative.
      if(!enabled || emergency)
         return false;

      // Preserve the existing position-capacity rule.
      if(maximumPositions <= 0)
         return false;

      if(currentPositions < 0)
         return false;

      if(currentPositions >= maximumPositions)
         return false;

      // Retained for compatibility with GoldScalperEA.mq5.
      // No additional intelligence-based entry filter.
      return true;
   }
};

#endif
