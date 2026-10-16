import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"

import { createClient } from "../../sdk/client"

function Directory(props: { projectId: string; path: string; name: string; onOpen: (path: string) => void }) {
  const client = useMemo(() => createClient(), [])
  const [open, setOpen] = useState(false)
  const tree = useQuery({
    queryKey: ["workspace-tree", props.projectId, props.path],
    queryFn: () => client.workspaceTree(props.projectId, props.path),
    enabled: open,
  })
  return (
    <div className="ml-3">
      <button type="button" onClick={() => setOpen((value) => !value)}>
        {props.name}
      </button>
      {open
        ? tree.data?.entries.map((entry) => {
            const child = `${props.path}/${entry.name}`
            return entry.type === "dir" ? (
              <Directory
                key={child}
                projectId={props.projectId}
                path={child}
                name={entry.name}
                onOpen={props.onOpen}
              />
            ) : (
              <button key={child} type="button" onClick={() => props.onOpen(child)}>
                {entry.name}
              </button>
            )
          })
        : null}
    </div>
  )
}

export function FileTree(props: {
  projectId: string
  onOpen: (path: string) => void
  onTarget: (target: string) => void
}) {
  const client = useMemo(() => createClient(), [])
  const tree = useQuery({
    queryKey: ["workspace-tree", props.projectId, ""],
    queryFn: () => client.workspaceTree(props.projectId, ""),
  })
  useEffect(() => {
    if (tree.data?.target_id) props.onTarget(tree.data.target_id)
  }, [props, tree.data])
  return (
    <div className="flex flex-wrap gap-2">
      {tree.data?.entries.map((entry) =>
        entry.type === "dir" ? (
          <Directory
            key={entry.name}
            projectId={props.projectId}
            path={entry.name}
            name={entry.name}
            onOpen={props.onOpen}
          />
        ) : (
          <button key={entry.name} type="button" onClick={() => props.onOpen(entry.name)}>
            {entry.name}
          </button>
        ),
      )}
    </div>
  )
}
