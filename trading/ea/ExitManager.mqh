
#ifndef GOLD_EXIT_MANAGER
#define GOLD_EXIT_MANAGER

#include <Trade/Trade.mqh>

class CExitManager
{
private:

   bool IsOurPosition(ulong ticket, string symbol, long magic)
   {
      if(ticket == 0)
         return false;

      if(!PositionSelectByTicket(ticket))
         return false;

      if(PositionGetString(POSITION_SYMBOL) != symbol)
         return false;

      if(PositionGetInteger(POSITION_MAGIC) != magic)
         return false;

      return true;
   }

   bool IsClosed(ulong ticket)
   {
      return !PositionSelectByTicket(ticket);
   }

public:

   // Close one specific broker position.
   bool ClosePosition(
      CTrade &trade,
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!IsOurPosition(ticket, symbol, magic))
         return IsClosed(ticket);

      bool requestAccepted = trade.PositionClose(ticket);

      uint retcode = trade.ResultRetcode();

      // Confirm the actual position state rather than trusting
      // the local request result alone.
      if(IsClosed(ticket))
         return true;

      Print(
         "Position remains open after close request. Ticket=",
         ticket,
         " RequestAccepted=",
         requestAccepted,
         " Retcode=",
         retcode,
         " Description=",
         trade.ResultRetcodeDescription()
      );

      return false;
   }

   // Close every position belonging to this EA and symbol.
   bool CloseAll(
      CTrade &trade,
      string symbol,
      long magic
   )
   {
      bool allClosed = true;

      // Iterate backwards because closing positions changes the list.
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);

         if(ticket == 0)
            continue;

         if(!IsOurPosition(ticket, symbol, magic))
            continue;

         if(!ClosePosition(trade, ticket, symbol, magic))
            allClosed = false;
      }

      // Final broker-side reconciliation.
      for(int j = PositionsTotal() - 1; j >= 0; j--)
      {
         ulong ticket = PositionGetTicket(j);

         if(ticket == 0)
            continue;

         if(IsOurPosition(ticket, symbol, magic))
            allClosed = false;
      }

      if(!allClosed)
      {
         Print(
            "CloseAll incomplete. Some matching positions remain open. ",
            "Symbol=",
            symbol,
            " Magic=",
            magic
         );
      }

      return allClosed;
   }
};

#endif
