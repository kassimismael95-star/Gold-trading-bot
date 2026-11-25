#ifndef GOLD_ENTRY_MANAGER
#define GOLD_ENTRY_MANAGER
class CEntryManager
{
public:
 bool CanEnter(int currentPositions,int maximumPositions,bool enabled,bool emergency,bool riskLocked)
 { return enabled && !emergency && !riskLocked && maximumPositions>0 && currentPositions<maximumPositions; }
};
#endif
