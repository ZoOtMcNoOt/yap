import { Copy } from "@phosphor-icons/react/Copy";
import { FolderOpen } from "@phosphor-icons/react/FolderOpen";
import { Sparkle as Sparkles } from "@phosphor-icons/react/Sparkle";
import { CloudArrowUp as UploadCloud } from "@phosphor-icons/react/CloudArrowUp";

import { StatusRow } from "@/components/app/status-row";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

export function HelpSheet({
  onOpenChange,
  onOpenSettings,
  open,
}: {
  onOpenChange: (open: boolean) => void;
  onOpenSettings?: () => void;
  open: boolean;
}) {
  return (
    <Sheet onOpenChange={onOpenChange} open={open}>
      <SheetContent
        className="w-[min(420px,calc(100vw-24px))] overflow-hidden sm:max-w-md"
        side="right"
      >
        <SheetHeader className="shrink-0">
          <SheetTitle>Help</SheetTitle>
          <SheetDescription>Recording, reading, and recovery.</SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4">
          <StatusRow
            icon={UploadCloud}
            label="Add files"
            value="Choose files or drag recordings onto Transcribe. They wait in the organization server queue."
            wrap
          />
          <StatusRow
            icon={Sparkles}
            label="Transcribe"
            value="Finished transcripts are saved locally and listed in History. Use Reveal to find a saved file."
            wrap
          />
          <StatusRow
            icon={Copy}
            label="Copy"
            value="Copies transcript text after a file finishes."
            wrap
          />
          <StatusRow
            icon={FolderOpen}
            label="Reveal"
            value="Shows the saved transcript in File Explorer."
            wrap
          />
          <section aria-label="Common questions" className="mt-2 grid gap-2">
            <h2 className="text-sm font-semibold">Common questions</h2>
            {[
              [
                "Do I need a model to use Yap?",
                "Local dictation needs an installed model. Imported recordings use your configured organization server. You can read saved transcripts and set up the app before either route is ready.",
              ],
              [
                "Which recordings can I import?",
                "WAV, MP3, FLAC and Ogg Vorbis/FLAC are supported. M4A and MP4 need one mono or stereo AAC-LC audio track. Fragmented files, complex edits and other codecs need conversion first; your original stays unchanged.",
              ],
              [
                "Why is my recording waiting?",
                "Imported recordings keep their organization-server route. Check the connection in Settings → System and choose the recording language in Transcribe. A server outage does not switch your recordings to local dictation.",
              ],
              [
                "Where is my transcript saved?",
                "Transcripts are stored locally and listed in Home. Use Reveal from the recording's actions to find its saved file.",
              ],
              [
                "Will correction change my original?",
                "Your original transcript stays unchanged. Review the proposed edits, then save to accept a separate correction revision.",
              ],
              [
                "Does a knowledge proposal publish anything?",
                "Proposals and conflict reports require human review. A created proposal includes a copyable reference for your organization's review process; it does not activate knowledge.",
              ],
            ].map(([question, answer]) => (
              <details className="rounded-lg border px-3 py-2" key={question}>
                <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {question}
                </summary>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {answer}
                </p>
              </details>
            ))}
            {onOpenSettings ? (
              <Button
                className="mt-1 w-fit"
                onClick={onOpenSettings}
                type="button"
                variant="outline"
              >
                Open Settings
              </Button>
            ) : null}
          </section>
        </div>
        <SheetFooter className="shrink-0">
          <SheetClose asChild>
            <Button type="button" variant="outline">
              Close
            </Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
