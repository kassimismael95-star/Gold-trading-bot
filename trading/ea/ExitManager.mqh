
#ifndef GOLD_EXIT_MANAGER
#define GOLD_EXIT_MANAGER

#include <Trade/Trade.mqh>

class CExitManager
{
private:

   bool IsOurPosition(
      ulong ticket,
      string symbol,
      long magic
   )
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

   bool IsSuccessfulRetcode(uint retcode)
   {
      return (
         retcode == TRADE_RETCODE_DONE ||
         retcode == TRADE_RETCODE_DONE_PARTIAL ||
         retcode == TRADE_RETCODE_PLACED
      );
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
      if(ticket == 0)
         return false;

      if(!IsOurPosition(ticket, symbol, magic))
         return IsClosed(ticket);

      bool requestAccepted = trade.PositionClose(ticket);

      uint retcode = trade.ResultRetcode();

      // Broker-side state is authoritative.
      if(IsClosed(ticket))
      {
         Print(
            "Position closure confirmed. Ticket=",
            ticket,
            " Retcode=",
            retcode
         );

         return true;
      }

      Print(
         "Position remains open after close request. ",
         "Ticket=",
         ticket,
         " RequestAccepted=",
         requestAccepted,
         " Retcode=",
         retcode,
         " SuccessfulRetcode=",
         IsSuccessfulRetcode(retcode),
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

   // Check whether a specific position still belongs to this EA.
   bool PositionIsManaged(
      ulong ticket,
      string symbol,
      long magic
   )
   {
      return IsOurPosition(ticket, symbol, magic);
   }

   // Close a position only when its identity still matches.
   bool CloseIfManaged(
      CTrade &trade,
      ulong ticket,
      string symbol,
      long magic
   )
   {
      if(!IsOurPosition(ticket, symbol, magic))
         return IsClosed(ticket);

      return ClosePosition(
         trade,
         ticket,
         symbol,
         magic
      );
   }
};

#endif
