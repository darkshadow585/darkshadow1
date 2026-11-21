/**
 * Context-aware safety shields, Captain addressing, and speech-friendly normalization.
 * Refined to avoid false positives on harmless queries like "git checkout" or "best camera phone"
 * while strictly blocking real payment execution, credentials, webcam activation, and destructive shells.
 */

const CAPTAIN_PATTERN = /\b(?:captain|कैप्टन)\b/i;

export function ensureCaptainAddress(text: string): string {
  const cleaned = text.trim();
  if (!cleaned) {
    return "Captain, mujhe khaali response mila. Kripya dobara try kijiye.";
  }
  if (CAPTAIN_PATTERN.test(cleaned)) {
    return cleaned;
  }
  return `Captain, ${cleaned}`;
}

export function speechFriendlyText(displayText: string): string {
  const replacements: Array<[RegExp, string]> = [
    [/\bCaptain\b/g, "कैप्टन"],
    [/\bcaptain\b/g, "कैप्टन"],
    [/\bNamaste\b/g, "नमस्ते"],
    [/\bnamaste\b/g, "नमस्ते"],
    [/\baap\b/g, "आप"],
    [/\bkijiye\b/g, "कीजिए"],
    [/\bdobara\b/g, "दोबारा"],
    [/\bsamajh\b/g, "समझ"],
    [/\bnahi\b/g, "नहीं"],
    [/\bhaan\b/g, "हाँ"],
    [/\btheek\b/g, "ठीक"],
  ];

  let result = displayText
    .replace(/```[\s\S]*?```/g, " code block ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "");

  for (const [pattern, target] of replacements) {
    result = result.replace(pattern, target);
  }
  return result.replace(/\s+/g, " ").trim();
}

const PAYMENT_PATTERNS =
  /\b(?:buy[-_ ]*now|place[-_ ]*order|proceed[-_ ]*to[-_ ]*pay|pay[-_ ]*now|complete[-_ ]*payment|payment\s*karo|pay\s*karo|kharid\s*lo|order\s*place\s*karo|complete\s*checkout|enter\s*cvv|enter\s*otp|upi[-_ ]*pin|atm[-_ ]*pin|credit[-_ ]*card\s*number|debit[-_ ]*card\s*number|card\s*details|bank\s*transfer\s*karo|भुगतान\s*करो|पेमेंट\s*करो|ऑर्डर\s*प्लेस)\b/i;

export const PAYMENT_BLOCKED_MESSAGE =
  "Security protocol: Automated payment, checkout aur financial credentials execution strictly blocked hai. Comparison available hai, par final payment kripya manually complete kijiye.";

export function isPaymentOrCheckoutIntent(text: string): boolean {
  if (!text) return false;
  // Allow developer git commands cleanly
  if (/\bgit\s+checkout\b/i.test(text)) return false;
  return PAYMENT_PATTERNS.test(text);
}

const PHYSICAL_CAMERA_PATTERNS =
  /\b(?:(?:open|start|turn\s*on|enable|activate)\s+(?:the\s+|my\s+)?(?:webcam|camera|cam)|(?:webcam|camera)\s*(?:on|kholo|chalao|start|open)|face[-_ ]*record(?:ing)?|record[-_ ]*(?:my\s+)?face|chehra\s*(?:dekho|dikhao|record)|take\s*(?:a\s+)?selfie|selfie\s*lo|photo\s*(?:khincho|lo)|कैमरा\s*(?:खोलो|चलाओ|ऑन)|वेबकैम\s*(?:खोलो|चलाओ)|चेहरा\s*देखो)\b/i;

export const CAMERA_BLOCKED_MESSAGE =
  "Privacy Protocol: Captain ki privacy ke mutabiq physical camera/webcam hardware access permanently disabled hai. Face ya room recording strictly blocked hai.";

export function isPhysicalCameraIntent(text: string): boolean {
  if (!text) return false;
  const cleaned = text.replace(/[-_]+/g, " ").trim();
  return PHYSICAL_CAMERA_PATTERNS.test(cleaned);
}

const DANGEROUS_TERMINAL_RULES: Array<[RegExp, string]> = [
  [/\bformat\s+[a-z]:/i, "Disk formatting is strictly blocked to protect your drives."],
  [/\b(?:diskpart|bootrec|bcdedit)\b/i, "Partition and boot record modification commands are strictly blocked."],
  [/\bcipher\s+\/[wW]/i, "Drive data wiping is blocked."],
  [/\b(?:del|erase|rmdir|rd|Remove-Item)\b.*?(?:[a-z]:\\|\\windows|\\system32|\bwindows\b|\bsystem32\b)/i, "System and root directory deletion is strictly blocked."],
  [/\brm\s+-[rf]+\s+.*?(?:\/|[a-z]:\\|\\windows|\\system32)/i, "Recursive force removal of system/root paths is blocked."],
  [/\breg\s+delete\s+.*(?:hklm|hkcr|hku)\b/i, "Deleting critical system registry hives is strictly blocked."],
  [/\bshutdown\s+\/[sSrR]/i, "Unconfirmed system shutdown/restart commands are blocked."],
  [/\b(?:iex|invoke-expression)\s*[({]|(?:downloadstring|downloadfile)\b/i, "Executing untrusted remote download scripts is blocked."],
  [/\bpowershell(?:\.exe)?\s+.*-(?:enc|encodedcommand)\b/i, "Obfuscated encoded PowerShell execution is blocked."],
  [/\|\s*(?:bash|powershell|cmd|iex)\b/i, "Piping untrusted network output into shell interpreters is blocked."],
  [/\bdrop\s+(?:database|schema)\b/i, "Database drop operations are blocked."],
];

export function isDangerousTerminalCommand(command: string): { blocked: boolean; reason: string } {
  const cleaned = command.trim();
  if (!cleaned) return { blocked: false, reason: "" };
  for (const [pattern, reason] of DANGEROUS_TERMINAL_RULES) {
    if (pattern.test(cleaned)) {
      return { blocked: true, reason: `Security Shield Blocked: ${reason}` };
    }
  }
  return { blocked: false, reason: "" };
}

const SENSITIVE_LABELS =
  /\b(?:api\s*key|password|passcode|passwd|otp|one[- ]time password|cvv|card\s*(?:number|no)|credit\s*card|debit\s*card|bank\s*account|upi\s*pin|private\s*key|secret\s*key|access\s*token|refresh\s*token|private\s*clipboard)\b/i;

const SECRET_SHAPES: RegExp[] = [
  /\bAIza[0-9A-Za-z_-]{20,}\b/,
  /\bAQ[0-9A-Za-z_-]{20,}\b/,
  /\bsk-[0-9A-Za-z_-]{16,}\b/i,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\b(?:\d{4}[ -]?){3}\d{4}\b/,
];

export function containsSensitiveData(content: string): boolean {
  const cleaned = content.trim();
  if (SENSITIVE_LABELS.test(cleaned)) return true;
  return SECRET_SHAPES.some((pattern) => pattern.test(cleaned));
}
