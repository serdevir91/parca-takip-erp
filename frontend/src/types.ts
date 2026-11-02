export type VersionBrief = {
  id: number; seq: number; filename: string; status: "pending" | "approved" | "rejected" | "undone" | string;
  uploaded_by: string | null; uploaded_at: string | null; approved_by: string | null; approved_at: string | null;
};

export type Project = {
  id: number; name: string; root_part_no: string; description: string; archived: boolean;
  created_at: string | null; current_version_id: number | null; current_version: VersionBrief | null;
  pending_versions: number; tracked_parts: number;
};
