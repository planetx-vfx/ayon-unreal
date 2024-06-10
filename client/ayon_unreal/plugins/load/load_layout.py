# -*- coding: utf-8 -*-
"""Loader for layouts."""
import json
import collections
from pathlib import Path

from ayon_api import (
    get_folder_by_name,
    get_folders,
    get_representations,
)
from ayon_core.pipeline import (
    discover_loader_plugins,
    loaders_from_representation,
    load_container,
    get_representation_path,
    AYON_CONTAINER_ID,
    get_current_project_name,
)
from ayon_core.pipeline.context_tools import get_current_folder_entity
from ayon_core.settings import get_current_project_settings
from ayon_unreal.api.plugin import UnrealBaseLoader
from ayon_unreal.api.pipeline import (
    send_request,
    containerise,
    imprint,
)


class LayoutLoader(UnrealBaseLoader):
    """Load Layout from a JSON file"""

    product_types = {"layout"}
    representations = {"json"}

    label = "Load Layout"
    icon = "code-fork"
    color = "orange"

    @staticmethod
    def _create_levels(
        hierarchy_dir_list, hierarchy, asset_dir, asset,
        create_sequences_option
    ):
        level = f"{asset_dir}/{asset}_map.{asset}_map"
        master_level = None

        if not send_request(
                "does_asset_exist", params={"asset_path": level}):
            send_request(
                "new_level",
                params={"level_path": f"{asset_dir}/{asset}_map"})

        if create_sequences_option:
            # Create map for the shot, and create hierarchy of map. If the
            # maps already exist, we will use them.
            if hierarchy:
                h_dir = hierarchy_dir_list[0]
                h_asset = hierarchy[0]
                master_level = f"{h_dir}/{h_asset}_map.{h_asset}_map"
                if not send_request(
                        "does_asset_exist",
                        params={"asset_path": master_level}):
                    send_request(
                        "new_level",
                        params={"level_path": f"{h_dir}/{h_asset}_map"})

            if master_level:
                send_request("load_level",
                             params={"level_path": master_level})
                send_request("add_level_to_world",
                             params={"level_path": level})
                send_request("save_all_dirty_levels")
                send_request("load_level", params={"level_path": level})

        return level, master_level

    @staticmethod
    def _get_frame_info(h_dir):
        project_name = get_current_project_name()
        asset_data = get_folder_by_name(
            project_name,
            h_dir.split('/')[-1],
            fields=["_id", "data.fps"]
        )

        start_frames = []
        end_frames = []

        elements = list(get_folders(
            project_name,
            parent_ids=[asset_data["_id"]],
            fields=["_id", "data.clipIn", "data.clipOut"]
        ))
        for e in elements:
            start_frames.append(e.get('data').get('clipIn'))
            end_frames.append(e.get('data').get('clipOut'))

            elements.extend(get_folders(
                project_name,
                parent_ids=[e["_id"]],
                fields=["_id", "data.clipIn", "data.clipOut"]
            ))

        min_frame = min(start_frames)
        max_frame = max(end_frames)

        return min_frame, max_frame, asset_data.get('data').get("fps")

    def _get_sequences(self, hierarchy_dir_list, hierarchy):
        # Get all the sequences in the hierarchy. It will create them, if
        # they don't exist.
        sequences = []
        frame_ranges = []
        for (h_dir, h) in zip(hierarchy_dir_list, hierarchy):
            root_content = send_request(
                "list_assets", params={
                    "directory_path": h_dir,
                    "recursive": False,
                    "include_folder": False})

            if existing_sequences := send_request(
                "get_assets_of_class",
                params={
                    "asset_list": root_content, "class_name": "LevelSequence"},
            ):
                for sequence in existing_sequences:
                    sequences.append(sequence)
                    frame_ranges.append(
                        send_request(
                            "get_sequence_frame_range",
                            params={"sequence_path": sequence}))
            else:
                start_frame, end_frame, fps = self._get_frame_info(h_dir)
                sequence = send_request(
                    "generate_sequence",
                    params={
                        "asset_name": h,
                        "asset_path": h_dir,
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "fps": fps})

                sequences.append(sequence)
                frame_ranges.append((start_frame, end_frame))

        return sequences, frame_ranges

    @staticmethod
    def _get_fbx_loader(loaders, family):
        name = ""
        if family == 'camera':
            name = "CameraLoader"
        elif family == 'model':
            name = "StaticMeshFBXLoader"
        elif family == 'rig':
            name = "SkeletalMeshFBXLoader"
        return (
            next(
                (
                    loader for loader in loaders if loader.__name__ == name
                ),
                None
            )
            if name
            else None
        )

    @staticmethod
    def _get_abc_loader(loaders, family):
        name = ""
        if family == 'model':
            name = "StaticMeshAlembicLoader"
        elif family == 'rig':
            name = "SkeletalMeshAlembicLoader"
        return (
            next(
                (
                    loader for loader in loaders if loader.__name__ == name
                ),
                None
            )
            if name
            else None
        )

    @staticmethod
    def _import_fbx_animation(
        asset_dir, path, instance_name, skeleton, animation_file
    ):
        anim_file_name = Path(animation_file).with_suffix('')

        anim_path = f"{asset_dir}/animations/{anim_file_name}"

        folder_entity = get_current_folder_entity()
        fps = folder_entity.get("attrib", {}).get("fps")

        options_properties = [
            ["automated_import_should_detect_type", "False"],
            ["original_import_type",
             "unreal.FBXImportType.FBXIT_SKELETAL_MESH"],
            ["mesh_type_to_import",
             "unreal.FBXImportType.FBXIT_ANIMATION"],
            ["import_mesh", "False"],
            ["import_animations", "True"],
            ["override_full_name", "True"],
            ["skeleton", f"get_asset({skeleton})"]
        ]

        sub_options_properties = [
            ["anim_sequence_import_data", "animation_length",
             "unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME"],
            ["anim_sequence_import_data",
             "import_meshes_in_bone_hierarchy", "False"],
            ["anim_sequence_import_data", "use_default_sample_rate", "False"],
            ["anim_sequence_import_data", "custom_sample_rate", str(fps)],
            ["anim_sequence_import_data", "import_custom_attribute", "True"],
            ["anim_sequence_import_data", "import_bone_tracks", "True"],
            ["anim_sequence_import_data", "remove_redundant_keys", "False"],
            ["anim_sequence_import_data", "convert_scene", "True"]
        ]

        params = {
            "filename": path.with_suffix(f".{animation_file}"),
            "destination_path": anim_path,
            "destination_name": f"{instance_name}_animation",
            "replace_existing": False,
            "automated": True,
            "save": True,
            "options_properties": options_properties,
            "sub_options_properties": sub_options_properties
        }

        send_request("import_fbx_task", params=params)

    @staticmethod
    def _process_animation(
        asset_dir, instance_name, actors_dict, bindings_dict, sequence
    ):
        asset_content = send_request(
            "list_assets", params={
                "directory_path": asset_dir,
                "recursive": True,
                "include_folder": True})

        animation = None

        if animations := send_request(
                "get_assets_of_class",
                params={"asset_list": asset_content,
                        "class_name": "AnimSequence"},
        ):
            animation = animations[0]

        if animation:
            actor = None
            if actors_dict.get(instance_name):
                actors = send_request(
                    "get_assets_of_class",
                    params={
                        "asset_list": actors_dict.get(instance_name),
                        "class_name": "SkeletalMeshActor"})
                assert len(actors) == 1, (
                    "There should be only one skeleton in the loaded assets.")
                actor = actors[0]

            send_request(
                "apply_animation_to_actor",
                params={
                    "actor_path": actor,
                    "animation_path": animation})

            if sequence:
                # Add animation to the sequencer
                bindings = bindings_dict.get(instance_name)

                for binding in bindings:
                    send_request(
                        "add_animation_to_sequencer",
                        params={
                            "sequence_path": sequence,
                            "binding_guid": binding,
                            "animation_path": animation})

    def _get_repre_entities_by_version_id(self, data):
        version_ids = {
            element.get("version")
            for element in data
            if element.get("representation")
        }
        version_ids.discard(None)

        output = collections.defaultdict(list)
        if not version_ids:
            return output

        project_name = get_current_project_name()
        repre_entities = get_representations(
            project_name,
            representation_names={"fbx", "abc"},
            version_ids=version_ids,
            fields={"id", "versionId", "name"}
        )
        for repre_entity in repre_entities:
            version_id = repre_entity["versionId"]
            output[version_id].append(repre_entity)
        return output

    def _get_representation(self, element, repre_entities_by_version_id):
        representation = None
        repr_format = None
        if element.get('representation'):
            version_id = element.get("version")
            repre_entities = repre_entities_by_version_id[version_id]
            if not repre_entities:
                self.log.error(
                    f"No valid representation found for version "
                    f"{version_id}")
                return None, None
            repre_entity = repre_entities[0]
            representation = str(repre_entity["_id"])
            repr_format = repre_entity["name"]

        # This is to keep compatibility with old versions of the
        # json format.
        elif element.get('reference_fbx'):
            representation = element.get('reference_fbx')
            repr_format = 'fbx'
        elif element.get('reference_abc'):
            representation = element.get('reference_abc')
            repr_format = 'abc'

        return representation, repr_format

    def _load_representation(
        self, product_type, representation, repr_format, instance_name,
        all_loaders
    ):
        loaders = loaders_from_representation(
            all_loaders, representation)

        loader = None

        if repr_format == 'fbx':
            loader = self._get_fbx_loader(loaders, product_type)
        elif repr_format == 'abc':
            loader = self._get_abc_loader(loaders, product_type)

        if not loader:
            self.log.error(
                f"No valid loader found for {representation}")
            return None, None, None

        assets = load_container(
            loader,
            representation,
            namespace=instance_name)

        asset_containers = send_request(
            "get_assets_of_class",
            params={
                "asset_list": assets,
                "class_name": "AyonAssetContainer"})

        assert len(asset_containers) == 1, (
            "There should be only one AyonAssetContainer in "
            "the loaded assets.")

        container = asset_containers[0]

        skeletons = send_request(
            "get_assets_of_class",
            params={
                "asset_list": assets,
                "class_name": "Skeleton"})
        assert len(skeletons) <= 1, (
            "There should be one skeleton at most in "
            "the loaded assets.")
        skeleton = skeletons[0] if skeletons else None
        return assets, container, skeleton

    @staticmethod
    def _process_instances(
        data, element, representation, product_type, sequence, assets
    ):
        actors_dict = {}
        bindings_dict = {}

        instances = [
            item for item in data
            if ((item.get('version') and
                 item.get('version') == element.get('version')) or
                item.get('reference_fbx') == representation or
                item.get('reference_abc') == representation)]

        for instance in instances:
            transform = str(instance.get('transform_matrix'))
            basis = str(instance.get('basis'))
            instance_name = instance.get('instance_name')

            if product_type == 'model':
                send_request(
                    "process_family",
                    params={
                        "assets": assets,
                        "class_name": 'StaticMesh',
                        "instance_name": instance_name,
                        "transform": transform,
                        "basis": basis,
                        "sequence_path": sequence})
            elif product_type == 'rig':
                (actors, bindings) = send_request(
                    "process_family",
                    params={
                        "assets": assets,
                        "class_name": 'SkeletalMesh',
                        "instance_name": instance_name,
                        "transform": transform,
                        "basis": basis,
                        "sequence_path": sequence})

                actors_dict[instance_name] = actors
                bindings_dict[instance_name] = bindings

        return actors_dict, bindings_dict

    def _process_assets(self, lib_path, asset_dir, sequence, repr_loaded=None):
        with open(lib_path, "r") as fp:
            data = json.load(fp)

        all_loaders = discover_loader_plugins()

        if not repr_loaded:
            repr_loaded = []

        path = Path(lib_path)

        skeleton_dict = {}
        actors_dict = {}
        bindings_dict = {}

        loaded_assets = []

        repre_entities_by_version_id = self._get_repre_entities_by_version_id(
            data
        )
        for element in data:
            representation, repr_format = self._get_representation(
                element, repre_entities_by_version_id)

            # If reference is None, this element is skipped, as it cannot be
            # imported in Unreal
            if not representation:
                continue

            instance_name = element.get('instance_name')

            skeleton = None

            if representation not in repr_loaded:
                repr_loaded.append(representation)

                product_type = element.get("product_type")
                if product_type is None:
                    product_type = element.get("family")

                assets, container, skeleton = self._load_representation(
                    product_type, representation, repr_format, instance_name,
                    all_loaders)

                loaded_assets.append(container)

                new_actors, new_bindings = self._process_instances(
                    data, element, representation, product_type, sequence,
                    assets)

                actors_dict |= new_actors
                bindings_dict |= new_bindings

                if skeleton:
                    skeleton_dict[representation] = skeleton
            else:
                skeleton = skeleton_dict.get(representation)

            animation_file = element.get('animation')

            if animation_file and skeleton:
                self._import_fbx_animation(
                    asset_dir, path, instance_name, skeleton, animation_file)

                self._process_animation(
                    asset_dir, instance_name, actors_dict,
                    bindings_dict, sequence)

        return loaded_assets

    def load(self, context, name=None, namespace=None, options=None):
        """Load and containerise representation into Content Browser.

        This is two step process. First, import FBX to temporary path and
        then call `containerise()` on it - this moves all content to new
        directory and then it will create AssetContainer there and imprint it
        with metadata. This will mark this path as container.

        Args:
            context (dict): application context
            name (str): Product name
            namespace (str): in Unreal this is basically path to container.
                             This is not passed here, so namespace is set
                             by `containerise()` because only then we know
                             real path.
            options (dict): Those would be data to be imprinted. This is not
                            used now, data are imprinted by `containerise()`.
        """
        data = get_current_project_settings()
        create_sequences = data["unreal"]["level_sequences_for_layouts"]

        # Create directory for asset and Ayon container
        folder_entity = context["folder"]
        folder_path = folder_entity["path"]
        hierarchy = folder_path.lstrip("/").split("/")

        hierarchy_dir = self.root
        hierarchy_dir_list = []
        for h in hierarchy:
            hierarchy_dir = f"{hierarchy_dir}/{h}"
            hierarchy_dir_list.append(hierarchy_dir)

        folder_name = hierarchy.pop(-1)
        asset_name = f"{folder_name}_{name}" if folder_name else name

        asset_dir, container_name = send_request(
            "create_unique_asset_name", params={
                "root": hierarchy_dir,
                "folder_name": folder_name,
                "name": name})

        send_request("make_directory", params={"directory_path": asset_dir})

        shot = None

        level, master_level = self._create_levels(
            hierarchy_dir_list, hierarchy, asset_dir, folder_name,
            create_sequences)

        if create_sequences:
            sequences, frame_ranges = self._get_sequences(
                hierarchy_dir_list, hierarchy)

            project_name = get_current_project_name()
            data = get_folder_by_name(project_name, folder_name)["data"]

            shot = send_request(
                "generate_layout_sequence",
                params={
                    "folder_name": folder_name,
                    "asset_dir": asset_dir,
                    "sequences": sequences,
                    "frame_ranges": frame_ranges,
                    "level": level,
                    "fps": data.get("fps"),
                    "clip_in": data.get("clipIn"),
                    "clip_out": data.get("clipOut")})

            send_request("load_level", params={"level_path": level})

        loaded_assets = self._process_assets(self.fname, asset_dir, shot)

        send_request(
            "save_listed_assets", params={"asset_list": loaded_assets})

        send_request("save_current_level")

        data = {
            "schema": "ayon:container-2.0",
            "id": AYON_CONTAINER_ID,
            "asset": folder_name,
            "folder_path": folder_path,
            "namespace": asset_dir,
            "container_name": container_name,
            "asset_name": asset_name,
            "loader": str(self.__class__.__name__),
            "representation": str(context["representation"]["id"]),
            "parent": str(context["representation"]["versionId"]),
            "family": context["product"]["productType"],
            "loaded_assets": loaded_assets
        }

        containerise(asset_dir, container_name, data)

        if master_level:
            send_request("load_level", params={"level_path": master_level})

        save_dir = hierarchy_dir_list[0] if create_sequences else asset_dir

        assets = send_request(
            "list_assets", params={
                "directory_path": save_dir,
                "recursive": True,
                "include_folder": False})

        send_request("save_listed_assets", params={"asset_list": assets})

        return assets

    def update(self, container, context):
        asset_dir = container.get('namespace')

        folder_entity = context["folder"]
        repre_entity = context["representation"]

        hierarchy = folder_entity["path"].lstrip("/").split("/")
        first_parent_name = hierarchy[0]

        data = get_current_project_settings()
        create_sequences = data["unreal"]["level_sequences_for_layouts"]

        sequence_path, curr_time, is_cam_lock, vp_loc, vp_rot = send_request(
            "get_current_sequence_and_level_info")

        sequence, master_level, prev_level = send_request(
            "update_layout", params={
                "asset_dir": asset_dir,
                "root": self.root,
                "hierarchy": hierarchy,
                "create_sequences": create_sequences})

        source_path = get_representation_path(repre_entity)

        loaded_assets = self._process_assets(source_path, asset_dir, sequence)

        data = {
            "representation": repre_entity["id"],
            "parent": repre_entity["versionId"],
            "loaded_assets": loaded_assets,
        }
        imprint(f"{asset_dir}/{container.get('objectName')}", data)

        send_request("save_current_level")

        save_dir = (
            f"{self.root}/{first_parent_name}"
            if create_sequences else asset_dir)

        if master_level:
            send_request("load_level", params={"level_path": master_level})
        elif prev_level:
            send_request("load_level", params={"level_path": prev_level})

        assets = send_request(
            "list_assets", params={
                "directory_path": save_dir,
                "recursive": True,
                "include_folder": False})

        send_request("save_listed_assets", params={"asset_list": assets})

        send_request(
            "set_current_sequence_and_level_info",
            params={
                "sequence_path": sequence_path,
                "curr_time": curr_time,
                "is_cam_lock": is_cam_lock,
                "vp_loc": vp_loc,
                "vp_rot": vp_rot})

    def remove(self, container):
        """
        Delete the layout. First, check if the assets loaded with the layout
        are used by other layouts. If not, delete the assets.
        """
        root = self.root
        asset = container.get('asset')
        asset_dir = container.get('namespace')
        asset_name = container.get('asset_name')
        loaded_assets = container.get('loaded_assets')

        data = get_current_project_settings()
        create_sequences_option = data["unreal"]["level_sequences_for_layouts"]

        send_request(
            "remove_layout",
            params={
                "root": root,
                "asset": asset,
                "asset_dir": asset_dir,
                "asset_name": asset_name,
                "loaded_assets": loaded_assets,
                "create_sequences": create_sequences_option})
