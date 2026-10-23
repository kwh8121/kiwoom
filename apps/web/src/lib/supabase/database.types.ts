
export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[]

export type Database = {

  "public": {
          Tables: {
            "broker_alias_owners": {
                  Row: {
                    "alias": string,"created_at": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "alias": string,"created_at"?: string,"user_id": string
                  }
                  Update: {
                    "alias"?: string,"created_at"?: string,"user_id"?: string
                  }
                  Relationships: [

                  ]
                },"broker_profiles": {
                  Row: {
                    "alias": string,"created_at": string,"display_name": string | null,"id": string,"last_error_code": string | null,"last_error_message": string | null,"last_ok_at": string | null,"mode": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "alias": string,"created_at"?: string,"display_name"?: string | null,"id"?: string,"last_error_code"?: string | null,"last_error_message"?: string | null,"last_ok_at"?: string | null,"mode": string,"user_id": string
                  }
                  Update: {
                    "alias"?: string,"created_at"?: string,"display_name"?: string | null,"id"?: string,"last_error_code"?: string | null,"last_error_message"?: string | null,"last_ok_at"?: string | null,"mode"?: string,"user_id"?: string
                  }
                  Relationships: [

                  ]
                },"condition_snapshot_members": {
                  Row: {
                    "change_rate": number | null,"code": string,"instrument_type": string,"name": string | null,"price": number | null,"raw_code": string,"snapshot_id": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "change_rate"?: number | null,"code": string,"instrument_type": string,"name"?: string | null,"price"?: number | null,"raw_code": string,"snapshot_id": string,"user_id": string
                  }
                  Update: {
                    "change_rate"?: number | null,"code"?: string,"instrument_type"?: string,"name"?: string | null,"price"?: number | null,"raw_code"?: string,"snapshot_id"?: string,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "condition_snapshot_members_snapshot_id_fkey"
      columns: ["snapshot_id"]
isOneToOne: false
      referencedRelation: "condition_snapshots"
      referencedColumns: ["id"]
    }
                  ]
                },"condition_snapshots": {
                  Row: {
                    "completed_at": string | null,"condition_id": string,"error_code": string | null,"id": string,"is_complete": boolean,"name": string,"page_count": number | null,"row_count": number | null,"run_id": string,"seq": string,"started_at": string | null,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "completed_at"?: string | null,"condition_id": string,"error_code"?: string | null,"id"?: string,"is_complete"?: boolean,"name": string,"page_count"?: number | null,"row_count"?: number | null,"run_id": string,"seq": string,"started_at"?: string | null,"user_id": string
                  }
                  Update: {
                    "completed_at"?: string | null,"condition_id"?: string,"error_code"?: string | null,"id"?: string,"is_complete"?: boolean,"name"?: string,"page_count"?: number | null,"row_count"?: number | null,"run_id"?: string,"seq"?: string,"started_at"?: string | null,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "condition_snapshots_condition_id_fkey"
      columns: ["condition_id"]
isOneToOne: false
      referencedRelation: "conditions"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "condition_snapshots_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "latest_profile_sync_runs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "condition_snapshots_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "runs"
      referencedColumns: ["id"]
    }
                  ]
                },"condition_sync_events": {
                  Row: {
                    "condition_id": string | null,"created_at": string,"event": string,"id": string,"new_name": string | null,"old_name": string | null,"profile_id": string,"run_id": string,"seq": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "condition_id"?: string | null,"created_at"?: string,"event": string,"id"?: string,"new_name"?: string | null,"old_name"?: string | null,"profile_id": string,"run_id": string,"seq": string,"user_id": string
                  }
                  Update: {
                    "condition_id"?: string | null,"created_at"?: string,"event"?: string,"id"?: string,"new_name"?: string | null,"old_name"?: string | null,"profile_id"?: string,"run_id"?: string,"seq"?: string,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "condition_sync_events_condition_id_fkey"
      columns: ["condition_id"]
isOneToOne: false
      referencedRelation: "conditions"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "condition_sync_events_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "broker_profiles"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "condition_sync_events_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "latest_profile_sync_runs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "condition_sync_events_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "runs"
      referencedColumns: ["id"]
    }
                  ]
                },"conditions": {
                  Row: {
                    "deactivated_at": string | null,"first_seen_at": string,"id": string,"is_active": boolean,"last_synced_at": string,"name": string,"profile_id": string,"ref_description": string | null,"seq": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "deactivated_at"?: string | null,"first_seen_at"?: string,"id"?: string,"is_active"?: boolean,"last_synced_at"?: string,"name": string,"profile_id": string,"ref_description"?: string | null,"seq": string,"user_id": string
                  }
                  Update: {
                    "deactivated_at"?: string | null,"first_seen_at"?: string,"id"?: string,"is_active"?: boolean,"last_synced_at"?: string,"name"?: string,"profile_id"?: string,"ref_description"?: string | null,"seq"?: string,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "conditions_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "broker_profiles"
      referencedColumns: ["id"]
    }
                  ]
                },"run_results": {
                  Row: {
                    "change_rate": number | null,"code": string,"diff": string,"instrument_type": string,"matched_condition_ids": (string)[],"name": string | null,"price": number | null,"run_id": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "change_rate"?: number | null,"code": string,"diff": string,"instrument_type": string,"matched_condition_ids"?: (string)[],"name"?: string | null,"price"?: number | null,"run_id": string,"user_id": string
                  }
                  Update: {
                    "change_rate"?: number | null,"code"?: string,"diff"?: string,"instrument_type"?: string,"matched_condition_ids"?: (string)[],"name"?: string | null,"price"?: number | null,"run_id"?: string,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "run_results_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "latest_profile_sync_runs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "run_results_run_id_fkey"
      columns: ["run_id"]
isOneToOne: false
      referencedRelation: "runs"
      referencedColumns: ["id"]
    }
                  ]
                },"runs": {
                  Row: {
                    "attempt": number,"compared_run_id": string | null,"error_code": string | null,"error_message": string | null,"excluded_codes": (string)[],"finished_at": string | null,"id": string,"idempotency_key": string,"kind": string,"lease_expires_at": string | null,"lease_owner": string | null,"market_phase": string | null,"max_attempts": number,"profile_id": string,"requested_at": string,"result_count": number | null,"started_at": string | null,"status": string,"strategy_id": string | null,"strategy_version_id": string | null,"sync_summary": Json | null,"user_id": string,"window_end": string | null,"window_start": string | null
                  }
                  ComputedFields: never
                  Insert: {
                    "attempt"?: number,"compared_run_id"?: string | null,"error_code"?: string | null,"error_message"?: string | null,"excluded_codes"?: (string)[],"finished_at"?: string | null,"id"?: string,"idempotency_key": string,"kind": string,"lease_expires_at"?: string | null,"lease_owner"?: string | null,"market_phase"?: string | null,"max_attempts"?: number,"profile_id": string,"requested_at"?: string,"result_count"?: number | null,"started_at"?: string | null,"status": string,"strategy_id"?: string | null,"strategy_version_id"?: string | null,"sync_summary"?: Json | null,"user_id": string,"window_end"?: string | null,"window_start"?: string | null
                  }
                  Update: {
                    "attempt"?: number,"compared_run_id"?: string | null,"error_code"?: string | null,"error_message"?: string | null,"excluded_codes"?: (string)[],"finished_at"?: string | null,"id"?: string,"idempotency_key"?: string,"kind"?: string,"lease_expires_at"?: string | null,"lease_owner"?: string | null,"market_phase"?: string | null,"max_attempts"?: number,"profile_id"?: string,"requested_at"?: string,"result_count"?: number | null,"started_at"?: string | null,"status"?: string,"strategy_id"?: string | null,"strategy_version_id"?: string | null,"sync_summary"?: Json | null,"user_id"?: string,"window_end"?: string | null,"window_start"?: string | null
                  }
                  Relationships: [
                    {
      foreignKeyName: "runs_compared_run_id_fkey"
      columns: ["compared_run_id"]
isOneToOne: false
      referencedRelation: "latest_profile_sync_runs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "runs_compared_run_id_fkey"
      columns: ["compared_run_id"]
isOneToOne: false
      referencedRelation: "runs"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "runs_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "broker_profiles"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "runs_strategy_id_fkey"
      columns: ["strategy_id"]
isOneToOne: false
      referencedRelation: "strategies"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "runs_strategy_version_id_fkey"
      columns: ["strategy_version_id"]
isOneToOne: false
      referencedRelation: "strategy_versions"
      referencedColumns: ["id"]
    }
                  ]
                },"strategies": {
                  Row: {
                    "archived_at": string | null,"created_at": string,"current_version_id": string | null,"id": string,"name": string,"profile_id": string,"updated_at": string,"user_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "archived_at"?: string | null,"created_at"?: string,"current_version_id"?: string | null,"id"?: string,"name": string,"profile_id": string,"updated_at"?: string,"user_id": string
                  }
                  Update: {
                    "archived_at"?: string | null,"created_at"?: string,"current_version_id"?: string | null,"id"?: string,"name"?: string,"profile_id"?: string,"updated_at"?: string,"user_id"?: string
                  }
                  Relationships: [
                    {
      foreignKeyName: "strategies_current_version_id_fkey"
      columns: ["current_version_id"]
isOneToOne: false
      referencedRelation: "strategy_versions"
      referencedColumns: ["id"]
    },{
      foreignKeyName: "strategies_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "broker_profiles"
      referencedColumns: ["id"]
    }
                  ]
                },"strategy_versions": {
                  Row: {
                    "condition_refs": NonNullable<Json>,"created_at": string,"definition": NonNullable<Json>,"id": string,"strategy_id": string,"user_id": string,"version": number
                  }
                  ComputedFields: never
                  Insert: {
                    "condition_refs": NonNullable<Json>,"created_at"?: string,"definition": NonNullable<Json>,"id"?: string,"strategy_id": string,"user_id": string,"version": number
                  }
                  Update: {
                    "condition_refs"?: NonNullable<Json>,"created_at"?: string,"definition"?: NonNullable<Json>,"id"?: string,"strategy_id"?: string,"user_id"?: string,"version"?: number
                  }
                  Relationships: [
                    {
      foreignKeyName: "strategy_versions_strategy_id_fkey"
      columns: ["strategy_id"]
isOneToOne: false
      referencedRelation: "strategies"
      referencedColumns: ["id"]
    }
                  ]
                },"worker_heartbeats": {
                  Row: {
                    "aliases": (string)[],"seen_at": string,"version": string,"worker_id": string
                  }
                  ComputedFields: never
                  Insert: {
                    "aliases": (string)[],"seen_at"?: string,"version": string,"worker_id": string
                  }
                  Update: {
                    "aliases"?: (string)[],"seen_at"?: string,"version"?: string,"worker_id"?: string
                  }
                  Relationships: [

                  ]
                }
          }
          Views: {
            "latest_profile_sync_runs": {
                  Row: {
                    "error_code": string | null,"id": string | null,"profile_id": string | null,"requested_at": string | null,"status": string | null,"sync_summary": Json | null
                  }
                  ComputedFields: never
                  Relationships: [
                    {
      foreignKeyName: "runs_profile_id_fkey"
      columns: ["profile_id"]
isOneToOne: false
      referencedRelation: "broker_profiles"
      referencedColumns: ["id"]
    }
                  ]
                },"my_worker_heartbeats": {
                  Row: {
                    "aliases": (string)[] | null,"seen_at": string | null,"worker_id": string | null
                  }
                  ComputedFields: never
                  Insert: {
                           "aliases"?: never,"seen_at"?: string | null,"worker_id"?: string | null
                         }
                        Update: {
                           "aliases"?: never,"seen_at"?: string | null,"worker_id"?: string | null
                         }
                        Relationships: [

                  ]
                }
          }
          Functions: {
            "cancel_run":
{ Args: { "p_run_id": string }; Returns: {
              "attempt": number,
"compared_run_id": string | null,
"error_code": string | null,
"error_message": string | null,
"excluded_codes": (string)[],
"finished_at": string | null,
"id": string,
"idempotency_key": string,
"kind": string,
"lease_expires_at": string | null,
"lease_owner": string | null,
"market_phase": string | null,
"max_attempts": number,
"profile_id": string,
"requested_at": string,
"result_count": number | null,
"started_at": string | null,
"status": string,
"strategy_id": string | null,
"strategy_version_id": string | null,
"sync_summary": Json | null,
"user_id": string,
"window_end": string | null,
"window_start": string | null
            }
                          SetofOptions: {
        from: "*"
        to: "runs"
        isOneToOne: true
        isSetofReturn: false
      } },
"create_strategy_version":
{ Args: { "p_definition": Json,"p_strategy_id": string }; Returns: {
              "condition_refs": NonNullable<Json>,
"created_at": string,
"definition": NonNullable<Json>,
"id": string,
"strategy_id": string,
"user_id": string,
"version": number
            }
                          SetofOptions: {
        from: "*"
        to: "strategy_versions"
        isOneToOne: true
        isSetofReturn: false
      } },
"request_run":
{ Args: { "p_idempotency_key": string,"p_kind": string,"p_profile_id": string,"p_strategy_id": string }; Returns: {
              "attempt": number,
"compared_run_id": string | null,
"error_code": string | null,
"error_message": string | null,
"excluded_codes": (string)[],
"finished_at": string | null,
"id": string,
"idempotency_key": string,
"kind": string,
"lease_expires_at": string | null,
"lease_owner": string | null,
"market_phase": string | null,
"max_attempts": number,
"profile_id": string,
"requested_at": string,
"result_count": number | null,
"started_at": string | null,
"status": string,
"strategy_id": string | null,
"strategy_version_id": string | null,
"sync_summary": Json | null,
"user_id": string,
"window_end": string | null,
"window_start": string | null
            }
                          SetofOptions: {
        from: "*"
        to: "runs"
        isOneToOne: true
        isSetofReturn: false
      } },
"strategy_leaf_ids":
{ Args: { "p_expr": Json }; Returns: (string)[]
                           }
          }
          Enums: {
            [_ in never]: never
          }
          CompositeTypes: {
            [_ in never]: never
          }
        }
}

type DatabaseWithoutInternals = Omit<Database, '__InternalSupabase'>

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
  ? (DefaultSchema["Tables"] & DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
      Row: infer R
    }
    ? R
    : never
  : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
  ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
      Insert: infer I
    }
    ? I
    : never
  : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never
> = DefaultSchemaTableNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
  ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
      Update: infer U
    }
    ? U
    : never
  : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never
> = DefaultSchemaEnumNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
  ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
  : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never
> = PublicCompositeTypeNameOrOptions extends { schema: keyof DatabaseWithoutInternals }
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
  ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
  : never

export const Constants = {
  "public": {
          Enums: {

          }
        }
} as const
