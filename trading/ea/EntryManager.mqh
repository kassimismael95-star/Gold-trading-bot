
#ifndef GOLD_ENTRY_MANAGER
#define GOLD_ENTRY_MANAGER

class CEntryManager
{
public:

   bool CanEnter(
      int currentPositions,
      int maximumPositions,
      bool enabled,
      bool emergency,
      bool riskLocked
   )
   {
      // Manual controls remain authoritative.
      if(!enabled || emergency)
         return false;

      // Position capacity remains part of the original entry rules.
      if(maximumPositions <= 0)
         return false;

      if(currentPositions >= maximumPositions)
         return false;

      // riskLocked is intentionally not used as an intelligence
      // entry filter. It is retained in the signature for compatibility
      // with the current GoldScalperEA.mq5.
      return true;
   }
};

#endif
