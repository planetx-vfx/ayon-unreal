# -*- coding: utf-8 -*-
from ayon_core.pipeline import CreatorError
from ayon_unreal.api.pipeline import (
    send_request,
)
from ayon_unreal.api.plugin import (
    UnrealAssetCreator
)
from ayon_core.lib import UILabelDef


class CreateLook(UnrealAssetCreator):
    """Shader connections defining shape look."""

    identifier = "io.ayon.creators.unreal.look"
    label = "Look"
    product_type = "look"
    icon = "paint-brush"

    def create(self, product_name, instance_data, pre_create_data):
        # We need to set this to True for the parent class to work
        pre_create_data["use_selection"] = True
        selection = send_request("get_selected_assets")

        if len(selection) != 1:
            raise CreatorError("Please select only one asset.")

        selected_asset = selection[0]

        look_directory = "/Game/Ayon/Looks"

        # Create the folder
        folder_name = send_request(
            "create_folder",
            params={"root": look_directory, "name": product_name})
        path = f"{look_directory}/{folder_name}"

        instance_data["look"] = path

        pre_create_data["members"] = send_request(
            "create_look",
            params={"path": path, "selected_asset": selected_asset})

        super(CreateLook, self).create(
            product_name,
            instance_data,
            pre_create_data)

    def get_pre_create_attr_defs(self):
        return [
            UILabelDef("Select the asset from which to create the look.")
        ]
